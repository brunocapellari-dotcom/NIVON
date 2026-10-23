"""Vigilância barata de versões CKAN ZARC sem baixar 211 MB a cada consulta.

Metadados são SINAIS de revisão: revision_id/last_modified do CKAN nunca
equivalem a SHA-256 do CSV. Só leitura de catálogo oficial e SQLite local
opcional. Sem publicações automáticas ou agendamento.
"""
from __future__ import annotations

import hashlib
import json
import sqlite3
from datetime import datetime, timezone

from .fontes_abertas_lote import consultar
from .transacoes_sqlite import savepoint_atomico

RESOURCE_ID="139e5a60-1f43-4cc8-aeab-a35dbbf816c0"
DATASET_ID="ZARC_JANELAS"
FONTE_ID="MAPA_ZARC"

class ErroZarcCKAN(ValueError):
    pass


def _timestamp(s):
    if not isinstance(s,str):
        raise ErroZarcCKAN("COLETA_SEM_TIMESTAMP")
    try:
        dt=datetime.fromisoformat(s.replace("Z","+00:00"))
    except ValueError as exc:
        raise ErroZarcCKAN("TIMESTAMP_COLETA_INVALIDO") from exc
    if dt.tzinfo is None or dt.utcoffset() is None:
        raise ErroZarcCKAN("FUSO_DA_COLETA_OBRIGATORIO")
    return dt.astimezone(timezone.utc).isoformat()


def normalizar_sinal(metadata:dict):
    if not isinstance(metadata,dict) or metadata.get("fonte_id")!=FONTE_ID:
        raise ErroZarcCKAN("CATALOGO_ZARC_INCOMPATIVEL")
    licenca=metadata.get("licenca_declarada")
    if not isinstance(licenca,str) or licenca.lower().strip() not in ("cc-by","cc-by-4.0","cc-by-3.0"):
        raise ErroZarcCKAN("LICENCA_CK_AN_NAO_RECONHECIDA")
    recursos=metadata.get("recursos")
    if not isinstance(recursos,list):
        raise ErroZarcCKAN("SEM_LISTA_RECURSOS")
    matching=[r for r in recursos if isinstance(r,dict) and r.get("id")==RESOURCE_ID]
    if len(matching)!=1:
        raise ErroZarcCKAN("RECURSO_2026_2027_AUSENTE_OU_DUPLICADO")
    r=matching[0]
    if r.get("formato")!="CSV":
        raise ErroZarcCKAN("RECURSO_NAO_CSV")
    url=r.get("url_somente_referencia")
    if (not isinstance(url,str) or not url.startswith("https://dados.agricultura.gov.br/")
            or not url.endswith("dados-abertos-tabua-de-risco-safra-2026-2027.csv")):
        raise ErroZarcCKAN("URL_RECURSO_CSV_DIVERGENTE")
    coleta=_timestamp(metadata.get("coleta"))
    def str_limited(x):
        return x if isinstance(x,str) and len(x)<=100 else None
    observado={
        "licenca_declarada":licenca.lower().strip(),
        "pacote_revision_id":str_limited(metadata.get("revision_id")),
        "pacote_modified":str_limited(metadata.get("atualizado_em")),
        "recurso_revision_id":str_limited(r.get("revision_id")),
        "recurso_modified":str_limited(r.get("atualizado_em")),
        "resource_id":RESOURCE_ID,"url_recurso":url,
    }
    serial=json.dumps(observado,sort_keys=True,ensure_ascii=False,
                      separators=(",",":")).encode("utf-8")
    fingerprint=hashlib.sha256(serial).hexdigest()
    return {
        **observado,
        "coleta_utc":coleta,
        "metadata_fingerprint":fingerprint,
        "source_id":"ZARC","dataset_id":DATASET_ID,
        "versao_csv_sha256":None,
        "consegue_provar_arquivo_alterado":False,
        "metadados_publicados_cientificamente":False,
    }


def abrir_historico_zarc_meta(path=":memory:"):
    db=sqlite3.connect(str(path),timeout=15)
    db.row_factory=sqlite3.Row
    db.execute("PRAGMA foreign_keys=ON")
    db.executescript("""
    CREATE TABLE IF NOT EXISTS zarc_sinais_ckan (
       recurso_id TEXT NOT NULL,
       coleta_utc TEXT NOT NULL,
       metadata_fingerprint TEXT NOT NULL CHECK(length(metadata_fingerprint)=64),
       pacote_revision_id TEXT,
       recurso_revision_id TEXT,
       pacote_modified TEXT,
       recurso_modified TEXT,
       licenca_declarada TEXT NOT NULL,
       PRIMARY KEY(recurso_id,coleta_utc)
    );
    CREATE INDEX IF NOT EXISTS idx_zarc_sinais_fingerprint
       ON zarc_sinais_ckan(recurso_id,metadata_fingerprint);
    """)
    return db


def registrar_sinal(db:sqlite3.Connection,observation:dict):
    if (not isinstance(observation,dict) or observation.get("resource_id")!=RESOURCE_ID
            or observation.get("dataset_id")!=DATASET_ID
            or observation.get("consegue_provar_arquivo_alterado") is not False):
        raise ErroZarcCKAN("OBSERVACAO_INCOMPATIVEL")
    coleta=_timestamp(observation.get("coleta_utc"))
    sha=observation.get("metadata_fingerprint")
    if not isinstance(sha,str) or len(sha)!=64 or any(c not in "0123456789abcdef" for c in sha):
        raise ErroZarcCKAN("HASH_METADATA_INVALIDO")
    with savepoint_atomico(db):
        prev=db.execute("""SELECT metadata_fingerprint FROM zarc_sinais_ckan
            WHERE recurso_id=? ORDER BY coleta_utc DESC LIMIT 1""",
            (RESOURCE_ID,)).fetchone()
        existing=db.execute("""SELECT metadata_fingerprint FROM zarc_sinais_ckan
            WHERE recurso_id=? AND coleta_utc=?""",(RESOURCE_ID,coleta)).fetchone()
        if existing is not None and existing[0]!=sha:
            raise ErroZarcCKAN("MESMA_COLETA_METADATA_DIVERGENTE")
        if existing is None:
            db.execute("""INSERT INTO zarc_sinais_ckan VALUES(?,?,?,?,?,?,?,?)""",
              (RESOURCE_ID,coleta,sha,
               observation.get("pacote_revision_id"),
               observation.get("recurso_revision_id"),
               observation.get("pacote_modified"),
               observation.get("recurso_modified"),
               observation.get("licenca_declarada")))
    mudou=prev is not None and prev[0]!=sha
    return {"dataset_id":DATASET_ID,
            "estado":"SINAL_METADATA_NAO_SHA_ARQUIVO",
            "observacoes":db.execute("SELECT COUNT(*) FROM zarc_sinais_ckan").fetchone()[0],
            "sinal_revision_changed":mudou,
            "sinal_sugere_reavaliacao_csv":mudou,
            "pode_afirmar_novo_csv":False,
            "csv_baixado":False,
            "atualizacao_agendada":False,
            "persistencia_agricola_real":False}


def verificar_fonte_ckan(*,executar=False,db=None):
    if executar is not True:
        raise PermissionError("REDE_OFF")
    metadata=consultar(FONTE_ID,executar=True)
    out=normalizar_sinal(metadata)
    if db is not None:
        info=registrar_sinal(db,out)
        return {**out,**info}
    return out
