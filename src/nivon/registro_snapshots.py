"""Livro-razão SQLite de snapshots de fontes NIVON, sem armazenar dados brutos.

Audita cada observação de arquivo/API, deduplica vintages por SHA e preserva
múltiplas datas de coleta. Não consulta rede, não publica e não autoriza coleta.
"""
from __future__ import annotations

import re
import sqlite3
from datetime import date, datetime, timezone

from .transacoes_sqlite import savepoint_atomico
from .zarc_licenca_manual import validar_licenca_manual


class ErroSnapshot(ValueError):
    pass


_SHA = re.compile(r"[0-9a-f]{64}\Z")
_IDENT = re.compile(r"[A-Z][A-Z0-9_]{2,90}\Z")
_COMPETENCIA = re.compile(r"[A-Za-z0-9][A-Za-z0-9/_-]{0,32}\Z")
_TIPOS = {"SINTETICO", "REAL_AUTORIZADO"}
# A ampliação de tamanho aplica-se APENAS ao snapshot TXT CONAB SICARM.
# Metadados persistidos, nunca os bytes ou registros individuais.
_LIMITE_PADRAO = 20_000_000
_LIMITE_POR_DATASET = {
    "CONAB_ARMAZENS_CAPACIDADE": 120_000_000,
    # Somente metadados/hash do CSV oficial ZARC (211.652.014 B medidos).
    "ZARC_JANELAS": 230_000_000,
    # CSV MDIC publicado por ano pode ultrapassar o limite padrão;
    # ledger armazena somente metadados e hashes, jamais os CSVs.
    "MDIC_COMEX_NCM": 1_500_000_000,
    "MDIC_COMEX_MUNICIPIO_SH4": 1_500_000_000,
}


def _instante(txt: str) -> str:
    if not isinstance(txt, str):
        raise ErroSnapshot("instante ISO obrigatório")
    try:
        v = datetime.fromisoformat(txt.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ErroSnapshot("instante ISO inválido") from exc
    if v.tzinfo is None or v.utcoffset() is None:
        raise ErroSnapshot("instante sem fuso")
    return v.astimezone(timezone.utc).isoformat()


def _data(txt: str | None) -> str | None:
    if txt is None:
        return None
    if not isinstance(txt, str) or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", txt):
        raise ErroSnapshot("data deve ser AAAA-MM-DD ou null")
    try:
        return date.fromisoformat(txt).isoformat()
    except ValueError as exc:
        raise ErroSnapshot("data inválida") from exc


def abrir_registro(caminho: str = ":memory:") -> sqlite3.Connection:
    db = sqlite3.connect(str(caminho), timeout=15)
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA foreign_keys = ON")
    db.executescript("""
        CREATE TABLE IF NOT EXISTS nivon_snapshots(
          id INTEGER PRIMARY KEY, dataset_id TEXT NOT NULL,
          fonte_id TEXT NOT NULL, sha256 TEXT NOT NULL,
          bytes INTEGER NOT NULL CHECK(bytes > 0),
          mime TEXT NOT NULL, schema_versao TEXT NOT NULL,
          competencia TEXT, referencia TEXT, publicacao TEXT,
          tipo TEXT NOT NULL CHECK(tipo IN ('SINTETICO','REAL_AUTORIZADO')),
          evidencia_direitos TEXT,
          UNIQUE(dataset_id, sha256)
        );
        CREATE TABLE IF NOT EXISTS nivon_coletas(
          snapshot_id INTEGER NOT NULL REFERENCES nivon_snapshots(id),
          coletado_utc TEXT NOT NULL,
          PRIMARY KEY(snapshot_id, coletado_utc)
        );
        CREATE INDEX IF NOT EXISTS idx_nivon_coletas_data
          ON nivon_coletas(coletado_utc);
    """)
    return db


def registrar_snapshot(db: sqlite3.Connection, catalogo: dict, *,
                       dataset_id: str, sha256: str, tamanho: int, mime: str,
                       schema_versao: str, coletado_em: str,
                       competencia: str | None = None,
                       referencia: str | None = None,
                       publicacao: str | None = None,
                       tipo: str = "SINTETICO",
                       autorizacoes: frozenset[str] = frozenset(),
                       evidencia_direitos: str | None = None,
                       licenca_manual=None) -> dict:
    """Registra proveniência, nunca os bytes. SINTETICO jamais implica direito real.

    Uma mesma versão (dataset + SHA) com semântica temporal divergente é conflito.
    Em dados reais exigem-se direitos específicos de COLETA e ARMAZENAMENTO.
    """
    if not isinstance(dataset_id, str) or not _IDENT.fullmatch(dataset_id):
        raise ErroSnapshot("dataset inválido")
    if not isinstance(catalogo, dict) or not isinstance(catalogo.get("datasets"), list):
        raise ErroSnapshot("catálogo ausente")
    match = [d for d in catalogo["datasets"] if d.get("id") == dataset_id]
    if len(match) != 1:
        raise ErroSnapshot("dataset fora do catálogo ou repetido")
    fonte_id = match[0]["source_id"]
    if (not isinstance(sha256, str) or not _SHA.fullmatch(sha256)
            or type(tamanho) is not int or not 0 < tamanho <= _LIMITE_POR_DATASET.get(dataset_id, _LIMITE_PADRAO)):
        raise ErroSnapshot("hash/tamanho inválido")
    # HTML somente para dataset LINEUP_* com validador próprio, não geral.
    mimes={"text/csv", "text/plain", "application/json", "application/pdf",
           "application/vnd.ms-excel",
           "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"}
    if dataset_id.startswith("LINEUP_"):
        mimes.add("text/html")
    if mime not in mimes:
        raise ErroSnapshot("MIME não homologado para o registro")
    if (not isinstance(schema_versao, str) or not 1 <= len(schema_versao) <= 80
            or not re.fullmatch(r"[A-Za-z0-9._-]+", schema_versao)):
        raise ErroSnapshot("schema inválido")
    coleta = _instante(coletado_em)
    pub, ref = _data(publicacao), _data(referencia)
    if pub is not None and pub > coleta[:10]:
        raise ErroSnapshot("publicação posterior à coleta")
    if competencia is not None and (not isinstance(competencia, str)
                                    or not _COMPETENCIA.fullmatch(competencia)):
        raise ErroSnapshot("competência inválida")
    if tipo not in _TIPOS:
        raise ErroSnapshot("tipo de snapshot desconhecido")
    if tipo == "REAL_AUTORIZADO":
        # Habilitação produtiva segue DENY-ALL. ÚNICA exceção explicitamente
        # controlada: ZARC CC-BY em quarentena MANUAL, sem cron/publicação.
        autorizado_producao=(match[0].get("enabled") is True
                and match[0].get("collection_authorized") is True)
        autorizado_manual=validar_licenca_manual(
            licenca_manual,dataset_id=dataset_id,evidence_id=evidencia_direitos)
        if not autorizado_producao and not autorizado_manual:
            raise PermissionError("snapshot real bloqueado: fonte sem autorização operacional")
        if not {"COLETA", "ARMAZENAMENTO"}.issubset(autorizacoes):
            raise PermissionError("direitos por operação não aprovados")
        if (not isinstance(evidencia_direitos, str) or not
                re.fullmatch(r"[A-Za-z0-9._:/-]{6,160}", evidencia_direitos)):
            raise PermissionError("identificador de evidência de direitos obrigatório")
    else:
        if evidencia_direitos is not None or autorizacoes or licenca_manual is not None:
            raise ErroSnapshot("snapshot sintético não pode simular autorização real")
    estado = (dataset_id, fonte_id, sha256, tamanho, mime, schema_versao,
              competencia, ref, pub, tipo, evidencia_direitos)
    with savepoint_atomico(db):
        anterior = db.execute("SELECT * FROM nivon_snapshots WHERE dataset_id=? AND sha256=?",
                              (dataset_id, sha256)).fetchone()
        nova_versao = anterior is None
        if anterior is not None:
            existente = tuple(anterior[k] for k in (
                "dataset_id", "fonte_id", "sha256", "bytes", "mime", "schema_versao",
                "competencia", "referencia", "publicacao", "tipo", "evidencia_direitos"))
            if existente != estado:
                raise ErroSnapshot("SHA repetido com metadados divergentes")
            sid = anterior["id"]
        else:
            sid = db.execute("""INSERT INTO nivon_snapshots
                (dataset_id,fonte_id,sha256,bytes,mime,schema_versao,competencia,
                 referencia,publicacao,tipo,evidencia_direitos)
                VALUES (?,?,?,?,?,?,?,?,?,?,?)""", estado).lastrowid
        existe = db.execute("SELECT 1 FROM nivon_coletas WHERE snapshot_id=? AND coletado_utc=?",
                            (sid, coleta)).fetchone()
        if existe is None:
            db.execute("INSERT INTO nivon_coletas VALUES (?,?)", (sid, coleta))
    return {"dataset_id": dataset_id, "fonte_id": fonte_id,
            "nova_versao": nova_versao, "nova_coleta": existe is None,
            "sha256": sha256, "coleta": coleta,
            "estado": "REGISTRO_PROVENIENCIA_NAO_HOMOLOGACAO",
            "publicacao": pub, "tipo": tipo}


def visao_asof(db: sqlite3.Connection, *, dataset_id: str, corte_coleta: str,
                corte_publicacao: str) -> dict | None:
    """Sem look-ahead: versões de publicação desconhecida não entram na visão."""
    corte = _instante(corte_coleta)
    pub = _data(corte_publicacao)
    if pub is None:
        raise ErroSnapshot("corte de publicação obrigatório")
    row = db.execute("""SELECT s.*,c.coletado_utc FROM nivon_coletas c
        JOIN nivon_snapshots s ON s.id=c.snapshot_id
        WHERE s.dataset_id=? AND s.publicacao IS NOT NULL
          AND s.publicacao<=? AND c.coletado_utc<=?
        ORDER BY s.publicacao DESC,c.coletado_utc DESC,s.sha256 DESC LIMIT 1""",
        (dataset_id, pub, corte)).fetchone()
    return dict(row) if row else None
