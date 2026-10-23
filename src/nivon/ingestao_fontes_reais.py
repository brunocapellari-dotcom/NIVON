"""Persistência operacional mínima e auditável do lote de fontes internacionais.

RAW imutável por SHA-256, lotes idempotentes e observações bitemporais.
Este SQLite é um estágio local durável, NÃO equivale a deploy no Google Cloud.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import sqlite3
import tempfile
from datetime import datetime, timezone
from pathlib import Path

_MAX_BYTES = 25_000_000
_ID = re.compile(r"^[A-Z][A-Z0-9_]{2,90}$")


class ErroIngestao(ValueError):
    pass


def _utc(valor):
    if isinstance(valor, datetime):
        dt = valor
    elif isinstance(valor, str):
        try:
            dt = datetime.fromisoformat(valor.replace("Z", "+00:00"))
        except ValueError as exc:
            raise ErroIngestao("instante ISO invalido") from exc
    else:
        raise ErroIngestao("timestamp ausente")
    if dt.utcoffset() is None:
        raise ErroIngestao("timestamp precisa timezone")
    return dt.astimezone(timezone.utc).isoformat()


def _identificador(value):
    if not isinstance(value, str) or not _ID.fullmatch(value):
        raise ErroIngestao("id fora do contrato")
    return value


def _abrir(banco):
    path = Path(banco)
    if path.is_symlink():
        raise ErroIngestao("symlink proibido para base")
    path.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(str(path), timeout=15)
    con.execute("PRAGMA busy_timeout=15000")
    con.execute("PRAGMA foreign_keys=ON")
    con.execute("PRAGMA journal_mode=WAL")
    con.executescript("""
    CREATE TABLE IF NOT EXISTS snapshots(
      snapshot_id TEXT PRIMARY KEY,
      dataset_id TEXT NOT NULL,
      url_publica TEXT NOT NULL,
      sha256 TEXT NOT NULL,
      coletado_em TEXT NOT NULL,
      content_type TEXT NOT NULL,
      tamanho INTEGER NOT NULL,
      arquivo TEXT NOT NULL,
      estado TEXT NOT NULL CHECK (estado IN ('RAW_RECEIVED','NORMALIZED','QUARANTINED')),
      UNIQUE(dataset_id,sha256)
    );
    CREATE TABLE IF NOT EXISTS observacoes(
      dataset_id TEXT NOT NULL,
      identidade TEXT NOT NULL,
      fingerprint TEXT NOT NULL,
      referencia TEXT NOT NULL,
      competencia TEXT,
      publicacao TEXT,
      coletado_em TEXT NOT NULL,
      unidade TEXT,
      valor TEXT,
      campos_json TEXT NOT NULL,
      snapshot_id TEXT NOT NULL REFERENCES snapshots(snapshot_id),
      natureza TEXT NOT NULL CHECK (natureza IN ('OBSERVADO','INFORMADO','ESTIMADO','PROJETADO','INFERIDO')),
      PRIMARY KEY(dataset_id, identidade, fingerprint)
    );
    CREATE INDEX IF NOT EXISTS idx_observacoes_asof
      ON observacoes(dataset_id,referencia,coletado_em);
    """)
    return con


def gravar_lote(*, banco, diretorio_bruto, dataset_id, origem, raw, tipo,
                coletado_em, registros=(), estado="RAW_RECEIVED"):
    """Grava RAW + linhas derivadas na mesma transação SQLite.

    Snapshot armazenado por SHA; não sobrescreve revisões anteriores.
    Dados de REGISTROS devem ser pré-validados pelo coletor de origem.
    """
    dataset_id = _identificador(dataset_id)
    coletado_em = _utc(coletado_em)
    if not isinstance(raw, bytes) or not 1 <= len(raw) <= _MAX_BYTES:
        raise ErroIngestao("raw vazio ou limite excedido")
    if not isinstance(origem, str) or not origem.startswith("https://") or any(x in origem for x in ("@", "#")):
        raise ErroIngestao("origem insegura")
    if estado not in ("RAW_RECEIVED", "NORMALIZED", "QUARANTINED"):
        raise ErroIngestao("estado invalido")
    if tipo not in ("text/csv", "application/json", "application/octet-stream", "application/vnd.ms-excel"):
        raise ErroIngestao("MIME nao permitido")
    if not isinstance(registros, (list, tuple)) or len(registros) > 20000:
        raise ErroIngestao("quantidade de observacoes invalida")
    sha = hashlib.sha256(raw).hexdigest()
    snapshot = hashlib.sha256((dataset_id + "|" + sha).encode()).hexdigest()
    root = Path(diretorio_bruto)
    if root.is_symlink():
        raise ErroIngestao("diretorio raw em symlink")
    targetdir = root / dataset_id
    targetdir.mkdir(parents=True, exist_ok=True)
    target = targetdir / (sha + ".raw")
    if target.is_symlink():
        raise ErroIngestao("arquivo raw em symlink")
    if not target.exists():
        handle, temp_name = tempfile.mkstemp(prefix=".raw-", dir=targetdir)
        try:
            with os.fdopen(handle, "wb") as out:
                out.write(raw)
                out.flush()
                os.fsync(out.fileno())
            os.replace(temp_name, target)
        finally:
            if os.path.exists(temp_name):
                os.unlink(temp_name)
    elif hashlib.sha256(target.read_bytes()).hexdigest() != sha:
        raise ErroIngestao("colisao ou raw corrompido")
    inseridos = 0
    with _abrir(banco) as db:
        db.execute("""INSERT OR IGNORE INTO snapshots
            (snapshot_id,dataset_id,url_publica,sha256,coletado_em,content_type,tamanho,arquivo,estado)
            VALUES(?,?,?,?,?,?,?,?,?)""",
            (snapshot,dataset_id,origem,sha,coletado_em,tipo,len(raw),str(target),estado))
        for row in registros:
            if not isinstance(row, dict) or not all(x in row for x in ("identidade","referencia","natureza","campos")):
                raise ErroIngestao("registro sem campos obrigatorios")
            identidade = str(row["identidade"])
            if not 1 <= len(identidade) <= 180 or row["natureza"] not in ("OBSERVADO","INFORMADO","ESTIMADO","PROJETADO","INFERIDO"):
                raise ErroIngestao("identidade/natureza invalida")
            campos = row["campos"]
            if not isinstance(campos, dict):
                raise ErroIngestao("campos nao mapeados")
            referencia = str(row["referencia"])
            if not re.fullmatch(r"\\d{4}-\\d{2}(-\\d{2})?", referencia):
                raise ErroIngestao("referencia invalida")
            texto = json.dumps(campos,sort_keys=True,ensure_ascii=False,allow_nan=False,separators=(",",":"))
            fingerprint = hashlib.sha256((identidade+"|"+referencia+"|"+texto).encode()).hexdigest()
            cur=db.execute("""INSERT OR IGNORE INTO observacoes
              (dataset_id,identidade,fingerprint,referencia,competencia,publicacao,coletado_em,unidade,valor,campos_json,snapshot_id,natureza)
              VALUES(?,?,?,?,?,?,?,?,?,?,?,?)""",
              (dataset_id,identidade,fingerprint,referencia,row.get("competencia"),
               row.get("publicacao"),coletado_em,row.get("unidade"),
               None if row.get("valor") is None else str(row["valor"]),texto,snapshot,row["natureza"]))
            inseridos+=cur.rowcount
    return {"dataset_id": dataset_id,"snapshot_id":snapshot,"sha256":sha,
            "novas_observacoes":inseridos, "total_observacoes_no_lote":len(registros),
            "estado":estado,"coletado_em":coletado_em,"arquivo_raw":str(target)}


def exportar_jsonl(*, banco, destino, dataset_id=None):
    """Gera arquivo para estágio BigQuery, sem afirmar carga no BigQuery."""
    if dataset_id is not None:
        _identificador(dataset_id)
    path=Path(destino)
    path.parent.mkdir(parents=True,exist_ok=True)
    con=_abrir(banco)
    try:
        rows=con.execute("""SELECT dataset_id,identidade,fingerprint,referencia,
                    competencia,publicacao,coletado_em,unidade,valor,
                    campos_json,snapshot_id,natureza FROM observacoes
                    WHERE (? IS NULL OR dataset_id=?) ORDER BY dataset_id,referencia,identidade,fingerprint""",
                    (dataset_id,dataset_id))
        n=0
        with path.open("w",encoding="utf-8") as fp:
            for x in rows:
                d=dict(zip(("dataset_id","identidade","fingerprint","referencia","competencia",
                   "publicacao","coletado_em","unidade","valor","campos","snapshot_id","natureza"),x))
                d["campos"]=json.loads(d["campos"])
                fp.write(json.dumps(d,ensure_ascii=False,sort_keys=True)+"\n")
                n+=1
        return {"arquivo":str(path),"observacoes":n,"destino":"STAGING_JSONL_NAO_ENVIADO"}
    finally:
        con.close()
