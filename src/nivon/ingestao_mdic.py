"""Pipeline local de CSV anual MDIC -> ledger de vintages -> SQLite agregado.

Nenhum download ou cópia bruta. Nenhum dado de empresa/posto é armazenado.
Padrão sintético; modo real exige gate de catálogo e direitos por operação.
"""
from __future__ import annotations
import json
import sqlite3
from datetime import datetime, timezone

from .mdic_stream import processar_arquivo_anual
from .registro_snapshots import registrar_snapshot, ErroSnapshot

class ErroIngestaoMDIC(ValueError):
    pass

def _utc(value: str) -> str:
    if not isinstance(value,str):raise ErroIngestaoMDIC("instante ISO obrigatório")
    try:d=datetime.fromisoformat(value.replace("Z","+00:00"))
    except ValueError as exc:raise ErroIngestaoMDIC("instante inválido") from exc
    if d.tzinfo is None or d.utcoffset() is None:
        raise ErroIngestaoMDIC("instante sem fuso")
    return d.astimezone(timezone.utc).isoformat()

def _tabelas(db:sqlite3.Connection)->None:
    db.execute("PRAGMA foreign_keys=ON")
    db.execute("""CREATE TABLE IF NOT EXISTS nivon_mdic_agregados(
        snapshot_id INTEGER PRIMARY KEY REFERENCES nivon_snapshots(id),
        ano INTEGER NOT NULL,
        direcao TEXT NOT NULL,
        granularidade TEXT NOT NULL,
        resultado_json TEXT NOT NULL
    )""")
    db.execute("""CREATE INDEX IF NOT EXISTS idx_mdic_ano_direcao
        ON nivon_mdic_agregados(ano,direcao,granularidade)""")

def _conferir_resumo(resumo:dict)->None:
    if resumo.get("situacao")!="ARQUIVO_LOCAL_NAO_HOMOLOGADO":
        raise ErroIngestaoMDIC("status de parser inesperado")
    totais=resumo["totais_arquivo_por_mes"]
    rows=resumo["recortes"]
    if not isinstance(totais,list) or not totais or not isinstance(rows,list) or not rows:
        raise ErroIngestaoMDIC("agregação sem dados")
    if sum(x["linhas"] for x in totais)!=resumo["linhas_total"]:
        raise ErroIngestaoMDIC("total de linhas em controle divergente")
    if sum(x["linhas_agrupadas"] for x in rows)!=resumo["linhas_filtradas"]:
        raise ErroIngestaoMDIC("linhas filtradas não conferem")
    mensal={x["competencia"]:x for x in totais}
    if len(mensal)!=len(totais):
        raise ErroIngestaoMDIC("mês duplicado")
    peso={}
    usd={}
    for x in rows:
        k=x["competencia"]
        if k not in mensal:raise ErroIngestaoMDIC("recorte sem total de mês")
        peso[k]=peso.get(k,0)+x["peso_liquido_kg"]
        usd[k]=usd.get(k,0)+x["valor_fob_usd"]
    if any(peso.get(k,0)>v["kg"] or usd.get(k,0)>v["fob_usd"]
           for k,v in mensal.items()):
        raise ErroIngestaoMDIC("recortes excedem totais do CSV")

def ingerir_arquivo_mdic(
    db:sqlite3.Connection,catalogo:dict,*,caminho,
    ano:int,direcao:str,granularidade:str,codigos:frozenset[str],
    coletado_em:str,tipo:str="SINTETICO",
    autorizacoes:frozenset[str]=frozenset(),evidencia_direitos:str|None=None,
    limite_bytes:int=1_500_000_000,
)->dict:
    """Só recebe arquivo local; não garante que a fonte seja oficial."""
    coleta=_utc(coletado_em)
    did="MDIC_COMEX_NCM" if granularidade=="NCM" else "MDIC_COMEX_MUNICIPIO_SH4"
    if granularidade not in ("NCM","MUNICIPIO_SH4"):
        raise ErroIngestaoMDIC("granularidade fora do contrato")
    if tipo=="REAL_AUTORIZADO":
        matches=[x for x in catalogo.get("datasets",[]) if x.get("id")==did]
        if (len(matches)!=1 or matches[0].get("enabled") is not True or
            matches[0].get("collection_authorized") is not True):
            raise PermissionError("MDIC real desabilitado no catálogo")
    resultado=processar_arquivo_anual(caminho,ano=ano,direcao=direcao,
        granularidade=granularidade,codigos=codigos,coletado_em=coleta,
        limite_bytes=limite_bytes)
    _conferir_resumo(resultado)
    snapshot=registrar_snapshot(db,catalogo,dataset_id=did,
        sha256=resultado["sha256_original"],tamanho=resultado["bytes_original"],
        mime="text/csv",schema_versao="MDIC_ANUAL_1",coletado_em=coleta,
        competencia=str(ano),publicacao=None,referencia=None,tipo=tipo,
        autorizacoes=autorizacoes,evidencia_direitos=evidencia_direitos)
    _tabelas(db)
    sid=db.execute("SELECT id FROM nivon_snapshots WHERE dataset_id=? AND sha256=?",
                   (did,resultado["sha256_original"])).fetchone()[0]
    normal=json.dumps({
        "recortes":resultado["recortes"],
        "totais_arquivo_por_mes":resultado["totais_arquivo_por_mes"],
        "linhas_total":resultado["linhas_total"],
        "linhas_filtradas":resultado["linhas_filtradas"],
    },ensure_ascii=False,sort_keys=True,separators=(",",":"),allow_nan=False)
    with db:
        previo=db.execute("SELECT * FROM nivon_mdic_agregados WHERE snapshot_id=?",(sid,)).fetchone()
        if previo is not None:
            if (previo["resultado_json"]!=normal or previo["ano"]!=ano or
                previo["direcao"]!=direcao or previo["granularidade"]!=granularidade):
                raise ErroIngestaoMDIC("SHA repetido com seleção/classificação divergente")
        else:
            db.execute("""INSERT INTO nivon_mdic_agregados
                (snapshot_id,ano,direcao,granularidade,resultado_json)
                VALUES (?,?,?,?,?)""",(sid,ano,direcao,granularidade,normal))
    return {"dataset_id":did,"sha256":resultado["sha256_original"],
            "ano":ano,"direcao":direcao,"granularidade":granularidade,
            "linhas_filtradas":resultado["linhas_filtradas"],
            "novo_snapshot":snapshot["nova_versao"],
            "nova_coleta":snapshot["nova_coleta"],
            "tipo":tipo,"publicacao":None,
            "estado":"AGREGADO_SQLITE_LOCAL_SEM_HOMOLOGACAO_NEM_PUBLICACAO"}

def observar_mdic_asof_coleta(
    db:sqlite3.Connection,*,dataset_id:str,ano:int,direcao:str,
    corte_coleta:str,incluir_sinteticos:bool=False
)->dict|None:
    """Última edição conhecida até a COLETA; não é backtest por publicação."""
    if dataset_id not in ("MDIC_COMEX_NCM","MDIC_COMEX_MUNICIPIO_SH4"):
        raise ErroIngestaoMDIC("dataset inválido")
    if type(ano) is not int or not 1997<=ano<=2100:
        raise ErroIngestaoMDIC("ano inválido")
    if direcao not in ("EXPORTACAO","IMPORTACAO"):
        raise ErroIngestaoMDIC("direção inválida")
    if type(incluir_sinteticos) is not bool:
        raise ErroIngestaoMDIC("incluir_sinteticos deve ser bool")
    corte=_utc(corte_coleta)
    _tabelas(db)
    rows=db.execute("""SELECT a.*,s.sha256,s.tipo,MAX(c.coletado_utc) AS visto_utc
        FROM nivon_mdic_agregados a
        JOIN nivon_snapshots s ON s.id=a.snapshot_id
        JOIN nivon_coletas c ON c.snapshot_id=s.id
        WHERE s.dataset_id=? AND a.ano=? AND a.direcao=?
        AND c.coletado_utc<=? AND (?=1 OR s.tipo='REAL_AUTORIZADO')
        GROUP BY a.snapshot_id
        ORDER BY visto_utc DESC, s.sha256 DESC LIMIT 2""",
        (dataset_id,ano,direcao,corte,int(incluir_sinteticos))).fetchall()
    if not rows:return None
    if (len(rows)>1 and rows[0]["visto_utc"]==rows[1]["visto_utc"]
        and rows[0]["sha256"]!=rows[1]["sha256"]):
        raise ErroIngestaoMDIC("revisões conflitantes no mesmo instante de coleta")
    row=rows[0]
    return {"dataset_id":dataset_id,"ano":ano,"direcao":direcao,
            "visto_utc":row["visto_utc"],"sha256":row["sha256"],
            "tipo":row["tipo"],"conteudo":json.loads(row["resultado_json"]),
            "ponto_no_tempo":"POR_COLETA_NAO_POR_PUBLICACAO",
            "dados_homologados":False,"publicacao_permitida":False}
