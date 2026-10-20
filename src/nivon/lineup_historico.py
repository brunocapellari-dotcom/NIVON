"""Line-up nacional: edições por porto em SQLite, sem scraping ou deploy.

Cada snapshot representa UMA publicação/edição. Seleciona edição inteira
para evitar misturar navios que saíram de programação em capturas posteriores.
Não transforma programação em operação ou tonelagem movimentada.
"""
from __future__ import annotations
import hashlib
import json
import re
import sqlite3
from datetime import datetime, timezone

from .lineup_nacional import normalizar_linha
from .registro_snapshots import registrar_snapshot
from .transacoes_sqlite import savepoint_atomico

class ErroHistoricoPortos(ValueError):
    pass

_SHA=re.compile(r"[0-9a-f]{64}\Z")
_MIMES=frozenset({"text/html","application/pdf"})

def _utc(x):
    if not isinstance(x,str):
        raise ErroHistoricoPortos("instante obrigatório")
    try:d=datetime.fromisoformat(x.replace("Z","+00:00"))
    except ValueError as exc:raise ErroHistoricoPortos("instante ISO inválido") from exc
    if d.tzinfo is None or d.utcoffset() is None:
        raise ErroHistoricoPortos("fuso obrigatório")
    return d.astimezone(timezone.utc).isoformat()

def preparar_historico(db):
    db.execute("PRAGMA foreign_keys=ON")
    db.execute("""CREATE TABLE IF NOT EXISTS nivon_lineup_edicoes(
        snapshot_id INTEGER PRIMARY KEY REFERENCES nivon_snapshots(id),
        porto_id TEXT NOT NULL,
        fonte_url TEXT NOT NULL,
        linhas INTEGER NOT NULL
    )""")
    db.execute("""CREATE TABLE IF NOT EXISTS nivon_lineup_linhas(
        snapshot_id INTEGER NOT NULL REFERENCES nivon_snapshots(id),
        seq INTEGER NOT NULL,observacao_json TEXT NOT NULL,
        PRIMARY KEY(snapshot_id,seq)
    )""")
    db.execute("CREATE INDEX IF NOT EXISTS idx_lineup_edicao_porto ON nivon_lineup_edicoes(porto_id)")

def guardar_edicao_lineup(
    db:sqlite3.Connection,catalogo:dict,escopo:dict,*,porto_id:str,
    registros:list[dict],sha256_origem:str,bytes_origem:int,
    mime_origem:str,coletado_em:str,tipo:str="SINTETICO",
    arquivo_origem:bytes|None=None,autorizacoes:frozenset[str]=frozenset(),
    evidencia_direitos:str|None=None
)->dict:
    """Dados normalizados entram sem bytes brutos; originais exigidos em REAL.

    A conferência SHA não prova que o parser extraiu fielmente cada linha.
    Direitos de publicação exigem homologação separada.
    """
    coleta=_utc(coletado_em)
    doc=next((p for p in escopo.get("ports",[]) if p.get("id")==porto_id),None)
    if doc is None or doc.get("live_enabled") is not False:
        raise ErroHistoricoPortos("porto fora do escopo ou ativação não homologada")
    dataset_id="LINEUP_"+porto_id
    if not isinstance(registros,list) or not 1<=len(registros)<=5000:
        raise ErroHistoricoPortos("edição vazia ou grande")
    if not isinstance(sha256_origem,str) or not _SHA.fullmatch(sha256_origem):
        raise ErroHistoricoPortos("hash inválido")
    if type(bytes_origem) is not int or not 0<bytes_origem<=20_000_000:
        raise ErroHistoricoPortos("tamanho do original fora do limite")
    if mime_origem not in _MIMES:raise ErroHistoricoPortos("tipo HTML/PDF não homologado")
    match=[x for x in catalogo.get("datasets",[]) if x.get("id")==dataset_id]
    if len(match)!=1:
        raise ErroHistoricoPortos("line-up ausente no catálogo")
    if tipo=="REAL_AUTORIZADO":
        if (match[0].get("enabled") is not True
            or match[0].get("collection_authorized") is not True
            or doc.get("commercial_rights")!="APPROVED"
            or doc.get("parser_homologated") is not True
            or doc.get("endpoint_verified") is not True):
            raise PermissionError("line-up real ainda não homologado para origem/direitos/parser")
        if arquivo_origem is None:
            raise PermissionError("line-up real exige bytes de evidência")
    if arquivo_origem is not None:
        if (not isinstance(arquivo_origem,bytes) or len(arquivo_origem)!=bytes_origem
                or hashlib.sha256(arquivo_origem).hexdigest()!=sha256_origem):
            raise ErroHistoricoPortos("original não corresponde ao hash/tamanho")
        if mime_origem=="application/pdf":
            if not arquivo_origem.startswith(b"%PDF-"):
                raise ErroHistoricoPortos("PDF sem assinatura")
        else:
            raw=arquivo_origem[:2048].lower()
            if b"request rejected" in raw or b"access denied" in raw:
                raise ErroHistoricoPortos("documento HTML parece WAF")
            if b"<table" not in arquivo_origem.lower():
                raise ErroHistoricoPortos("HTML sem tabela compatível")
    canon=[]
    publicacao=set()
    fonte=set()
    for linha in registros:
        r=normalizar_linha(linha,escopo)
        if r["porto_id"]!=porto_id or _utc(r["coletado_em"])!=coleta:
            raise ErroHistoricoPortos("edição mistura porto ou instante")
        publicacao.add(r["publicado_em"][:10])
        fonte.add(r["fonte_url"])
        # Preservar a identidade da edição sem gravar a data da coleta no conteúdo.
        conteudo={k:v for k,v in r.items() if k!="coletado_em"}
        canon.append(json.dumps(conteudo,ensure_ascii=False,
                   sort_keys=True,separators=(",",":"),allow_nan=False))
    if len(fonte)!=1 or len(publicacao)!=1:
        raise ErroHistoricoPortos("edição mistura proveniência ou datas publicadas")
    fonte_url=fonte.pop()
    if tipo=="REAL_AUTORIZADO" and fonte_url!=doc.get("lineup_source_url"):
        raise PermissionError("URL real diverge do recurso portuário homologado")
    preparado=(porto_id,fonte_url,len(canon))
    preparar_historico(db)
    with savepoint_atomico(db):
        anterior=db.execute("""SELECT e.porto_id,e.fonte_url,e.linhas,e.snapshot_id
            FROM nivon_lineup_edicoes e JOIN nivon_snapshots s ON s.id=e.snapshot_id
            WHERE s.dataset_id=? AND s.sha256=?""",(dataset_id,sha256_origem)).fetchone()
        if anterior:
            old=db.execute("""SELECT observacao_json FROM nivon_lineup_linhas
                WHERE snapshot_id=? ORDER BY seq""",(anterior["snapshot_id"],)).fetchall()
            if (tuple(anterior[k] for k in ("porto_id","fonte_url","linhas"))!=preparado
                    or [x[0] for x in old]!=canon):
                raise ErroHistoricoPortos("mesmo SHA com conteúdo/linhas divergentes")
        registrado=registrar_snapshot(db,catalogo,dataset_id=dataset_id,
             sha256=sha256_origem,tamanho=bytes_origem,mime=mime_origem,
             schema_versao="LINEUP_NACIONAL_1",coletado_em=coleta,
             publicacao=publicacao.pop(),tipo=tipo,
             autorizacoes=autorizacoes,evidencia_direitos=evidencia_direitos)
        sid=db.execute("SELECT id FROM nivon_snapshots WHERE dataset_id=? AND sha256=?",
                       (dataset_id,sha256_origem)).fetchone()[0]
        if not anterior:
            db.execute("INSERT INTO nivon_lineup_edicoes VALUES (?,?,?,?)",
                       (sid,*preparado))
            db.executemany("INSERT INTO nivon_lineup_linhas VALUES (?,?,?)",
                           [(sid,i,raw) for i,raw in enumerate(canon)])
    return {"dataset_id":dataset_id,"linhas":len(canon),
            "nova_versao":registrado["nova_versao"],
            "nova_coleta":registrado["nova_coleta"],
            "hash_comprovado_por_bytes":arquivo_origem is not None,
            "situacao":"HISTORICO_LOCAL_NAO_HOMOLOGADO_NEM_REALIZADO"}

def edicao_lineup_asof(db,*,porto_id:str,corte_coleta:str,
                       incluir_sinteticos:bool=False)->dict|None:
    coleta=_utc(corte_coleta)
    if not isinstance(porto_id,str) or not re.fullmatch(r"[A-Z0-9_]{3,90}",porto_id):
        raise ErroHistoricoPortos("identificador de porto inválido")
    if type(incluir_sinteticos) is not bool:
        raise ErroHistoricoPortos("incluir_sinteticos inválido")
    preparar_historico(db)
    rows=db.execute("""SELECT s.id,s.sha256,s.tipo,s.publicacao,
                 MAX(c.coletado_utc) AS coletado_utc
            FROM nivon_lineup_edicoes e
            JOIN nivon_snapshots s ON s.id=e.snapshot_id
            JOIN nivon_coletas c ON c.snapshot_id=s.id
            WHERE e.porto_id=? AND s.dataset_id=? AND c.coletado_utc<=?
              AND (?=1 OR s.tipo='REAL_AUTORIZADO')
            GROUP BY s.id ORDER BY coletado_utc DESC,s.sha256 DESC LIMIT 2""",
          (porto_id,"LINEUP_"+porto_id,coleta,int(incluir_sinteticos))).fetchall()
    if not rows:return None
    if (len(rows)>1 and rows[0]["coletado_utc"]==rows[1]["coletado_utc"]
            and rows[0]["sha256"]!=rows[1]["sha256"]):
        raise ErroHistoricoPortos("edições distintas na mesma coleta: ambiguidade")
    versao=rows[0]
    registros=[{**json.loads(x[0]),"coletado_em":versao["coletado_utc"]}
        for x in db.execute("""SELECT observacao_json FROM nivon_lineup_linhas
            WHERE snapshot_id=? ORDER BY seq""",(versao["id"],)).fetchall()]
    return {"porto_id":porto_id,"sha256":versao["sha256"],
        "coletado_utc":versao["coletado_utc"],"publicacao":versao["publicacao"],
        "linhas":registros,"edicao_completa":True,
        "evidencia_realizacao_validada":False,
        "licenca_publicacao_homologada":False,
        "tipo_temporal":"ASOF_DATA_DE_COLETA_NAO_MOVIMENTACAO_ANTAQ"}
