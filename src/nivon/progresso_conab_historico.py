"""CONAB progresso semanal: armazenamento local versionado e consultas por coleta.

Recebe apenas registros JÁ normalizados por conab_agrobr; jamais coleta rede.
Preserva MEDIA_ESTADOS separado dos 27 estados e não calcula Brasil por média.
"""
from __future__ import annotations

import json
import re
import sqlite3
from datetime import datetime, timezone

from .registro_snapshots import registrar_snapshot
from .transacoes_sqlite import savepoint_atomico

class ErroProgressoHistorico(ValueError):
    pass

_UFS=frozenset("AC AL AM AP BA CE DF ES GO MA MG MS MT PA PB PE PI PR RJ RN RO RR RS SC SE SP TO".split())
_CAMPOS=frozenset({
    "source_id","dataset_id","cultura","safra","operacao","uf",
    "competencia","referencia","publicacao","coleta","source_url",
    "observational_kind","revisado","n_estados","cobertura_area_pct",
    "pct_ano_anterior","pct_semana_anterior","pct_semana_atual","pct_media_5_anos",
})
_CHAVE=("cultura","safra","operacao","uf","competencia")

def _utc(data):
    if not isinstance(data,str):raise ErroProgressoHistorico("timestamp ISO obrigatório")
    try:d=datetime.fromisoformat(data.replace("Z","+00:00"))
    except ValueError as exc:raise ErroProgressoHistorico("timestamp ISO inválido") from exc
    if d.tzinfo is None or d.utcoffset() is None:
        raise ErroProgressoHistorico("timestamp sem fuso")
    return d.astimezone(timezone.utc).isoformat()

def preparar_esquema(db:sqlite3.Connection):
    db.execute("PRAGMA foreign_keys=ON")
    db.execute("""CREATE TABLE IF NOT EXISTS nivon_conab_progresso(
        snapshot_id INTEGER NOT NULL REFERENCES nivon_snapshots(id),
        chave TEXT NOT NULL, observacao_json TEXT NOT NULL,
        PRIMARY KEY(snapshot_id,chave)
    )""")
    db.execute("CREATE INDEX IF NOT EXISTS idx_progresso_chave ON nivon_conab_progresso(chave)")

def _canonic(registros,coleta):
    if not isinstance(registros,(list,tuple)) or not 1<=len(registros)<=5000:
        raise ErroProgressoHistorico("1 a 5000 registros normalizados requeridos")
    itens=[]
    chaves=set()
    pubs=set()
    for dado in registros:
        if not isinstance(dado,dict) or set(dado)!=_CAMPOS:
            raise ErroProgressoHistorico("campos de progresso alterados")
        if dado["dataset_id"]!="CONAB_PROGRESSO_SEMANAL" or dado["source_id"]!="CONAB":
            raise ErroProgressoHistorico("dataset/fonte divergentes")
        if _utc(dado["coleta"])!=coleta:
            raise ErroProgressoHistorico("coleta em horários diferentes no mesmo arquivo")
        if dado["operacao"] not in ("Semeadura","Colheita"):
            raise ErroProgressoHistorico("operação divergente")
        uf=dado["uf"]
        if uf not in _UFS and uf!="MEDIA_ESTADOS":
            raise ErroProgressoHistorico("estado ausente ou país inferido por média simples")
        if dado["observational_kind"]!="INFORMADO":
            raise ErroProgressoHistorico("classificação temporal não observada")
        if dado["referencia"]!=dado["competencia"] or not re.fullmatch(r"20\d{2}-[01]\d-[0-3]\d",dado["competencia"]):
            raise ErroProgressoHistorico("semana/referência divergentes")
        if not isinstance(dado["cultura"],str) or not dado["cultura"].strip():
            raise ErroProgressoHistorico("cultura vazia")
        if not isinstance(dado["safra"],str) or not dado["safra"].strip():
            raise ErroProgressoHistorico("safra vazia")
        for campo in ("pct_semana_atual","pct_semana_anterior","pct_ano_anterior","pct_media_5_anos"):
            val=dado[campo]
            if val is not None and (type(val) not in (float,int) or not 0<=val<=1):
                raise ErroProgressoHistorico("percentual inválido")
        if dado["pct_semana_atual"] is None:
            raise ErroProgressoHistorico("sem percentual atual: não inventar zero")
        if uf=="MEDIA_ESTADOS":
            if type(dado["n_estados"]) is not int or not 1<=dado["n_estados"]<=27:
                raise ErroProgressoHistorico("média de estados sem cobertura explicitada")
        if dado["publicacao"] is not None:
            pub=_utc(dado["publicacao"])
            if pub>coleta:raise ErroProgressoHistorico("publicação posterior à coleta")
            pubs.add(pub[:10])
        else:pubs.add(None)
        chave=json.dumps([dado[x] for x in _CHAVE],separators=(",",":"),ensure_ascii=False)
        if chave in chaves:raise ErroProgressoHistorico("cultura/safra/UF/semana duplicada")
        chaves.add(chave)
        # Hora de captura pertence ao ledger de coletas, NÃO ao conteúdo da edição.
        # A mesma planilha, capturada novamente, deve ser idempotente.
        conteudo={k:v for k,v in dado.items() if k!="coleta"}
        itens.append((chave,json.dumps(conteudo,ensure_ascii=False,
                 sort_keys=True,separators=(",",":"),allow_nan=False)))
    if len(pubs)!=1:raise ErroProgressoHistorico("publicação mista ou desconhecida em parte do arquivo")
    return itens,pubs.pop()

def registrar_progresso_local(
    db:sqlite3.Connection,catalogo:dict,*,registros:list[dict],
    sha256_origem:str,bytes_origem:int,mime_origem:str,
    coletado_em:str,tipo:str="SINTETICO",
    autorizacoes:frozenset[str]=frozenset(),evidencia_direitos:str|None=None,
)->dict:
    """SHA e bytes da fonte são informados pelo caller; NÃO verificados aqui.

    Modo REAL exige catálogo+direitos e futura auditoria independente dos bytes.
    """
    coleta=_utc(coletado_em)
    if tipo=="REAL_AUTORIZADO":
        matches=[x for x in catalogo.get("datasets",[]) if x.get("id")=="CONAB_PROGRESSO_SEMANAL"]
        if len(matches)!=1 or matches[0].get("enabled") is not True or matches[0].get("collection_authorized") is not True:
            raise PermissionError("CONAB progresso real desabilitado no catálogo")
    dados,publicacao=_canonic(registros,coleta)
    preparar_esquema(db)
    with savepoint_atomico(db):
        # Testar conflito ANTES de registrar uma nova coleta.
        old=db.execute("""SELECT p.chave,p.observacao_json FROM nivon_conab_progresso p
            JOIN nivon_snapshots s ON s.id=p.snapshot_id
            WHERE s.dataset_id=? AND s.sha256=?""",
            ("CONAB_PROGRESSO_SEMANAL",sha256_origem)).fetchall()
        if old and dict(old)!=dict(dados):
            raise ErroProgressoHistorico("mesma fonte/hash com registros divergentes")
        snapshot=registrar_snapshot(db,catalogo,
            dataset_id="CONAB_PROGRESSO_SEMANAL",sha256=sha256_origem,
            tamanho=bytes_origem,mime=mime_origem,schema_versao="CONAB_PROG_1",
            coletado_em=coleta,competencia=None,referencia=None,
            publicacao=publicacao,tipo=tipo,
            autorizacoes=autorizacoes,evidencia_direitos=evidencia_direitos)
        sid=db.execute("SELECT id FROM nivon_snapshots WHERE dataset_id=? AND sha256=?",
            ("CONAB_PROGRESSO_SEMANAL",sha256_origem)).fetchone()[0]
        if not old:
            db.executemany("INSERT INTO nivon_conab_progresso VALUES(?,?,?)",
                [(sid,k,v) for k,v in dados])
    return {"dataset_id":"CONAB_PROGRESSO_SEMANAL","linhas":len(dados),
            "sha256_informado":sha256_origem,
            "nova_versao":snapshot["nova_versao"],"nova_coleta":snapshot["nova_coleta"],
            "estado":"VERSAO_SQLITE_SEM_HOMOLOGACAO_DE_FONTE_OU_PUBLICACAO"}

def consultar_progresso_asof(db:sqlite3.Connection,*,corte_coleta:str,
                             cultura:str,safra:str,operacao:str,uf:str,
                             incluir_sinteticos:bool=False)->dict:
    corte=_utc(corte_coleta)
    if uf not in _UFS and uf!="MEDIA_ESTADOS":
        raise ErroProgressoHistorico("UF inválida")
    if operacao not in ("Semeadura","Colheita") or not cultura or not safra:
        raise ErroProgressoHistorico("filtros incompletos")
    if type(incluir_sinteticos) is not bool:
        raise ErroProgressoHistorico("incluir_sinteticos deve ser booleano")
    preparar_esquema(db)
    rows=db.execute("""SELECT p.observacao_json,s.sha256,c.coletado_utc,s.tipo
        FROM nivon_conab_progresso p
        JOIN nivon_snapshots s ON s.id=p.snapshot_id
        JOIN nivon_coletas c ON c.snapshot_id=s.id
        WHERE s.dataset_id='CONAB_PROGRESSO_SEMANAL'
          AND c.coletado_utc<=? AND (?=1 OR s.tipo='REAL_AUTORIZADO')
        ORDER BY c.coletado_utc DESC,s.sha256 DESC LIMIT 20001""",
        (corte,int(incluir_sinteticos))).fetchall()
    if len(rows)>20000:
        raise ErroProgressoHistorico("janela extensa: consulta paginada necessária")
    saida={}
    for row in rows:
        d=json.loads(row["observacao_json"])
        if (d["cultura"],d["safra"],d["operacao"],d["uf"])!=(cultura,safra,operacao,uf):
            continue
        key=d["competencia"]
        if key in saida:
            anterior=saida[key]
            if (anterior["coletado_utc"]==row["coletado_utc"] and
                    anterior["sha256"]!=row["sha256"] and
                    anterior["dados"]!=d):
                raise ErroProgressoHistorico("revisões simultâneas conflitantes")
        else:
            saida[key]={"dados":d,"coletado_utc":row["coletado_utc"],"sha256":row["sha256"]}
    return {"cultura":cultura,"safra":safra,"operacao":operacao,"uf":uf,
            "semanas":[saida[k] for k in sorted(saida)],
            "media_estados_nao_e_brasil":uf=="MEDIA_ESTADOS",
            "asof":"COLETA_NAO_EQUIVALE_A_PUBLICACAO",
            "publicacao_liberada":False}
