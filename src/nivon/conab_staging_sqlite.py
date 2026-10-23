"""SQLite local de capturas CONAB, separado de históricos agrícolas/vintages.

Persistência de metadados e pequenas amostras de layout, NUNCA dados de safra
homologados. Cada SHA da mesma edição é preservado; não sobrescrever revisões.
Nenhuma operação de rede ou Google Cloud, sem merge ou deploy.
"""
from __future__ import annotations

from hashlib import sha256
import json
import re
import sqlite3

from .conab_lote_offline import ErroLoteConab

_SHA = re.compile(r"[a-f0-9]{64}\Z")
_SAFRA = re.compile(r"20\d\d/\d\d\Z")
_SCHEMA = """
CREATE TABLE IF NOT EXISTS nivon_conab_staging_documentos (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  safra TEXT NOT NULL, numero_levantamento INTEGER NOT NULL,
  arquivo_sha256 TEXT NOT NULL,
  url_documento TEXT NOT NULL,
  captura_primeira_utc TEXT NOT NULL,
  captura_ultima_utc TEXT NOT NULL,
  html_levantamento_sha256 TEXT NOT NULL,
  html_anexo_sha256 TEXT NOT NULL,
  layout_json TEXT NOT NULL,
  classe_status TEXT NOT NULL CHECK(classe_status='OFFLINE_SEM_VINTAGE'),
  UNIQUE(safra, numero_levantamento, arquivo_sha256)
);
CREATE INDEX IF NOT EXISTS idx_conab_staging_edicao
ON nivon_conab_staging_documentos(safra, numero_levantamento);
"""


def preparar_staging(db: sqlite3.Connection) -> None:
    db.execute("PRAGMA foreign_keys=ON")
    db.executescript(_SCHEMA)


def gravar_dossie_conab(db: sqlite3.Connection, dossie: dict) -> dict:
    """Inserção transacional e idempotente; hashes distintos nunca são apagados.

    Reprova lote com documentos rejeitados para evitar publicação parcial.
    Se houver mais de um SHA na mesma edição, classifica capturas distintas
    sem declarar "revisão de valores oficiais" ou disponibilidade histórica.
    """
    if (not isinstance(dossie, dict) or
            dossie.get("status") != "DOSSIER_STAGING_NAO_HOMOLOGADO" or
            dossie.get("habilita_publicacao") is not False or
            dossie.get("habilita_treino") is not False or
            dossie.get("habilita_backtest") is not False or
            dossie.get("edicao_historica_autenticada") is not False or
            dossie.get("captura_real_verificada_externamente") is not False):
        raise ErroLoteConab("dossiê operacional ou sem proveniência de staging")
    entries=dossie.get("resultados")
    if (not isinstance(entries, list) or not 1 <= len(entries) <= 30 or
            dossie.get("rejeitados") != 0 or
            dossie.get("inspecionados") != len(entries) or
            dossie.get("total") != len(entries)):
        raise ErroLoteConab("lote rejeitado, incompleto ou incongruente")
    prepared=[]
    identities=set()
    for item in entries:
        if (not isinstance(item, dict) or
                item.get("resultado") != "INSPECAO_OFFLINE_CONCLUIDA" or
                item.get("habilita_backtest") is not False or
                item.get("habilita_treino") is not False or
                item.get("habilita_publicacao") is not False):
            raise ErroLoteConab("documento não é uma inspeção offline")
        vinculo=item.get("vinculo")
        layout=item.get("amostra_layout")
        if not isinstance(vinculo, dict) or not isinstance(layout, dict):
            raise ErroLoteConab("vínculo ou amostra ausente")
        if (vinculo.get("edicao_historica_autenticada") is not False or
                layout.get("tabela_agricola_normalizada") is not False or
                layout.get("edicao_historica_autenticada") is not False or
                layout.get("habilita_publicacao") is not False or
                layout.get("habilita_backtest") is not False):
            raise ErroLoteConab("tentativa de promoção da amostra para série")
        digest=vinculo.get("arquivo_raw_sha256")
        if (not isinstance(digest, str) or not _SHA.fullmatch(digest) or
                layout.get("arquivo_raw_sha256") != digest):
            raise ErroLoteConab("hash da amostra não corresponde ao vínculo")
        safra=vinculo.get("safra")
        n=vinculo.get("numero_levantamento")
        if (not isinstance(safra, str) or not _SAFRA.fullmatch(safra) or
                type(n) is not int or not 1 <= n <= 12):
            raise ErroLoteConab("identidade de edição inválida")
        for k in ("levantamento_html_sha256","anexo_html_sha256"):
            h=vinculo.get(k)
            if not isinstance(h, str) or not _SHA.fullmatch(h):
                raise ErroLoteConab("hash do HTML ausente")
        identity=(safra,n,digest)
        if identity in identities:
            raise ErroLoteConab("documento duplicado no dossiê")
        identities.add(identity)
        safe=json.dumps(layout,ensure_ascii=False,sort_keys=True,
                        separators=(",",":"),allow_nan=False)
        if len(safe.encode("utf-8")) > 180_000:
            raise ErroLoteConab("amostra de layout excessiva")
        prepared.append((
            safra,n,digest,vinculo.get("arquivo_xlsx_url"),
            vinculo.get("captura_primeira_utc"),vinculo.get("captura_ultima_utc"),
            vinculo["levantamento_html_sha256"],vinculo["anexo_html_sha256"],
            safe,"OFFLINE_SEM_VINTAGE",
        ))
    stats={"recebidos":len(prepared),"inseridos":0,"duplicatas_idempotentes":0,
           "novos_shas_mesma_edicao":0,
           "edicao_historica_autenticada":False,
           "habilita_backtest":False,"habilita_treino":False,
           "habilita_publicacao":False}
    with db:
        for row in prepared:
            safra,n,digest=row[:3]
            older=db.execute(
                """SELECT arquivo_sha256 FROM nivon_conab_staging_documentos
                WHERE safra=? AND numero_levantamento=? LIMIT 1""",(safra,n)
            ).fetchone()
            existing=db.execute(
                """SELECT url_documento,captura_primeira_utc,
                 captura_ultima_utc,html_levantamento_sha256,
                 html_anexo_sha256,layout_json
                 FROM nivon_conab_staging_documentos
                 WHERE safra=? AND numero_levantamento=? AND arquivo_sha256=?""",
                (safra,n,digest)
            ).fetchone()
            if existing:
                # Mesmo SHA para XLSX pode ter metadado HTML novo; preservar
                # registro original e distinguir ao relatar divergência.
                if existing[0] != row[3] or existing[-1] != row[8]:
                    raise ErroLoteConab(
                        "mesmo SHA com URL ou layout conflitante; requer auditoria"
                    )
                stats["duplicatas_idempotentes"] += 1
                continue
            db.execute(
                """INSERT INTO nivon_conab_staging_documentos
                (safra,numero_levantamento,arquivo_sha256,url_documento,
                captura_primeira_utc,captura_ultima_utc,
                html_levantamento_sha256,html_anexo_sha256,layout_json,classe_status)
                VALUES (?,?,?,?,?,?,?,?,?,?)""",row
            )
            stats["inseridos"] += 1
            if older:
                stats["novos_shas_mesma_edicao"] += 1
    return stats
