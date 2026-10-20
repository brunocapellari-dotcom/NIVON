"""Vínculo de proveniência entre RAW NASA e registro canônico de snapshots.

O ledger armazena apenas hash/metadados; RAW permanece em SQLite próprio.
Nenhuma importação NASA atual se torna vintage histórica sem publicação provada.
"""
from __future__ import annotations
from datetime import datetime
from hashlib import sha256
from urllib.parse import urlsplit,parse_qs
import sqlite3

from .pipeline_historico_nasa import DATASET,HistoricoNASA
from .registro_snapshots import registrar_snapshot
from .qualidade_cientifica import ErroCientifico


def vincular_nasa_ao_ledger(*,raw:HistoricoNASA,ledger:sqlite3.Connection,
                           catalogo:dict,sha:str,
                           autorizacoes:frozenset[str]=frozenset(),
                           evidencia_direitos:str|None=None)->dict:
    if not isinstance(raw,HistoricoNASA) or not isinstance(sha,str) or len(sha)!=64:
        raise ErroCientifico("armazém/hash RAW NASA inválido")
    row=raw.conn.execute("SELECT * FROM raw_nasa WHERE raw_sha256=?",(sha,)).fetchone()
    if row is None or row["dataset_id"]!=DATASET or row["fonte_id"]!="NASA_POWER":
        raise ErroCientifico("snapshot não consta no RAW canônico")
    payload=bytes(row["raw_bytes"])
    if sha256(payload).hexdigest()!=sha:
        raise ErroCientifico("RAW NASA adulterado")
    url=row["request_url"]
    if sha256(url.encode()).hexdigest()!=row["request_sha256"]:
        raise ErroCientifico("URL de origem alterada")
    if row["modo"]!=raw.modo:
        raise ErroCientifico("modo RAW e armazenamento incompatíveis")
    parts=urlsplit(url)
    if parts.scheme!="https" or parts.hostname!="power.larc.nasa.gov":
        raise ErroCientifico("host de origem inválido")
    args=parse_qs(parts.query,strict_parsing=True)
    try:
        inicio=datetime.strptime(args["start"][0],"%Y%m%d").date()
        fim=datetime.strptime(args["end"][0],"%Y%m%d").date()
        standard=args["time-standard"][0]
    except (ValueError,KeyError,IndexError) as exc:
        raise ErroCientifico("datas e padrão UTC ausentes") from exc
    if standard!="UTC" or inicio.year!=fim.year or inicio>fim:
        raise ErroCientifico("request deve ser de um único ano UTC")
    real=raw.modo=="IMPORTACAO_AUTORIZADA"
    if real:
        if not row["direitos_ref"] or row["direitos_ref"]!=evidencia_direitos:
            raise PermissionError("direitos do RAW e ledger divergentes")
        tipo="REAL_AUTORIZADO"
    else:
        if autorizacoes or evidencia_direitos is not None:
            raise ErroCientifico("fixture nunca pode ser promovido a fonte real")
        tipo="SINTETICO"
    info=registrar_snapshot(
        ledger,catalogo,dataset_id=DATASET,sha256=sha,tamanho=len(payload),
        mime="application/json",schema_versao="NASA_POWER_DAILY_UTC_V1",
        coletado_em=row["coletado_em_utc"],competencia=str(inicio.year),
        referencia=inicio.isoformat(),publicacao=None,tipo=tipo,
        autorizacoes=autorizacoes,evidencia_direitos=evidencia_direitos)
    return {**info,"status":"LEDGER_VINCULADO_SEM_HOMOLOGACAO",
            "raw_sha256":sha,"publicacao_conhecida":False,
            "backtest_historico_asof_permitido":False}
