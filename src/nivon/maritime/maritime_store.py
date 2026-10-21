"""Storage AIS local, reproduzivel e deny-by-default; NAO e servico cloud 24x7."""
from __future__ import annotations

import hashlib
import json
import os
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def _utc(value: str | datetime) -> str:
    try:
        dt = value if isinstance(value, datetime) else datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (TypeError, ValueError) as exc:
        raise ValueError("instante invalido") from exc
    if dt.tzinfo is None or dt.utcoffset() is None:
        raise ValueError("timezone obrigatorio")
    return dt.astimezone(timezone.utc).isoformat()


class MaritimeStore:
    """SQLite transportavel para ensaios e operacao licenciada local.

    O backup nao substitui persistencia remota + restauracao homologadas.
    """

    def __init__(self, path: str | Path = ":memory:") -> None:
        file = str(path)
        if file != ":memory:" and Path(file).is_symlink():
            raise ValueError("recusa arquivo de armazenamento simbolico")
        self.path = file
        self.db = sqlite3.connect(file, timeout=10)
        if file != ":memory:":
            os.chmod(file, 0o600)
            self.db.execute("PRAGMA journal_mode=WAL")
        self.db.execute("PRAGMA foreign_keys=ON")
        self.db.execute("PRAGMA busy_timeout=5000")
        self.db.executescript("""
            CREATE TABLE IF NOT EXISTS maritime_ais (
                event_id TEXT PRIMARY KEY,
                source_id TEXT NOT NULL,
                port_id TEXT,
                mmsi TEXT,
                observed_at TEXT NOT NULL,
                collected_at TEXT NOT NULL,
                quality_status TEXT NOT NULL,
                payload_sha256 TEXT NOT NULL,
                payload_json TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_ais_port_time
              ON maritime_ais(port_id, observed_at);
            CREATE INDEX IF NOT EXISTS idx_ais_mmsi_time
              ON maritime_ais(mmsi, observed_at);
            CREATE TABLE IF NOT EXISTS maritime_lineup (
                snapshot_id TEXT PRIMARY KEY,
                source_id TEXT NOT NULL,
                port_id TEXT NOT NULL,
                collected_at TEXT NOT NULL,
                payload_sha256 TEXT NOT NULL,
                payload_json TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_lineup_port_time
              ON maritime_lineup(port_id, collected_at);
        """)
        self.db.commit()

    def __enter__(self) -> "MaritimeStore":
        return self

    def __exit__(self, *_: object) -> None:
        self.close()

    def close(self) -> None:
        self.db.close()

    @staticmethod
    def _payload(obj: dict[str, Any]) -> tuple[str, str]:
        if not isinstance(obj, dict):
            raise ValueError("payload invalido")
        raw = json.dumps(obj, ensure_ascii=False, sort_keys=True, separators=(",", ":"),
                         default=str, allow_nan=False)
        if len(raw.encode("utf-8")) > 2_000_000:
            raise ValueError("payload excede limite")
        return raw, hashlib.sha256(raw.encode("utf-8")).hexdigest()

    def save_ais(self, row: dict[str, Any], *, source_id: str,
                 collected_at: str | datetime, storage_authorized: bool = False,
                 port_id: str | None = None, quality_status: str = "UNVALIDATED") -> bool:
        if not storage_authorized:
            raise PermissionError("captura AIS nao autorizada para armazenamento")
        if not source_id.strip():
            raise ValueError("source_id obrigatorio")
        raw, checksum = self._payload(row)
        observed = _utc(row.get("observed_at"))
        collected = _utc(collected_at)
        if quality_status not in {"QUARANTINE", "UNCONFIRMED_SINGLE", "CONFIRMED_SEQUENCE", "UNVALIDATED"}:
            raise ValueError("status de qualidade desconhecido")
        key = hashlib.sha256((source_id + "|" + checksum).encode("utf-8")).hexdigest()
        with self.db:
            cur = self.db.execute("""
              INSERT OR IGNORE INTO maritime_ais
                (event_id,source_id,port_id,mmsi,observed_at,collected_at,quality_status,payload_sha256,payload_json)
              VALUES (?,?,?,?,?,?,?,?,?)
            """, (key, source_id, port_id.upper() if port_id else None,
                  str(row.get("mmsi") or ""), observed, collected, quality_status, checksum, raw))
        return cur.rowcount == 1

    def save_lineup(self, snapshot: dict[str, Any], *, source_id: str, port_id: str,
                    collected_at: str | datetime, storage_authorized: bool = False) -> bool:
        if not storage_authorized:
            raise PermissionError("lineup nao autorizado para armazenamento")
        if not source_id.strip() or not port_id.strip():
            raise ValueError("fonte e porto obrigatorios")
        raw, checksum = self._payload(snapshot)
        collected = _utc(collected_at)
        key = hashlib.sha256(
            (source_id + "|" + port_id.upper() + "|" + collected + "|" + checksum).encode("utf-8")
        ).hexdigest()
        with self.db:
            cur = self.db.execute("""
               INSERT OR IGNORE INTO maritime_lineup
               (snapshot_id,source_id,port_id,collected_at,payload_sha256,payload_json)
               VALUES (?,?,?,?,?,?)
            """, (key, source_id, port_id.upper(), collected, checksum, raw))
        return cur.rowcount == 1

    def replay(self, *, port_id: str, start: str | datetime, end: str | datetime,
               limit: int = 1000) -> list[dict[str, Any]]:
        if not port_id.strip() or not 1 <= limit <= 5000:
            raise ValueError("porto ou limite invalido")
        start_utc, end_utc = _utc(start), _utc(end)
        if end_utc < start_utc:
            raise ValueError("janela invertida")
        cursor = self.db.execute("""
           SELECT event_id,source_id,observed_at,collected_at,quality_status,payload_json
           FROM maritime_ais WHERE port_id=? AND observed_at>=? AND observed_at<=?
           ORDER BY observed_at ASC,event_id ASC LIMIT ?
        """, (port_id.upper(), start_utc, end_utc, limit))
        return [
            {
                "observation_id": identity, "source_id": source,
                "observed_at": observed, "collected_at": collected,
                "quality_status": quality, "raw": json.loads(payload),
            }
            for identity, source, observed, collected, quality, payload in cursor
        ]

    def backup(self, destination: str | Path, *, backup_authorized: bool = False) -> dict[str, Any]:
        if not backup_authorized:
            raise PermissionError("backup requer autorizacao")
        dst = Path(destination)
        if dst.is_symlink() or dst.exists():
            raise ValueError("destino ja existe ou e link simbolico")
        dst.parent.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(str(dst)) as out:
            self.db.backup(out)
            status = out.execute("PRAGMA integrity_check").fetchone()[0]
            if status != "ok":
                raise RuntimeError("backup corrompido")
        os.chmod(dst, 0o600)
        digest = hashlib.sha256(dst.read_bytes()).hexdigest()
        return {"path": str(dst), "sha256": digest, "integrity": "ok"}

    @staticmethod
    def validate_restore(source: str | Path) -> dict[str, Any]:
        path = Path(source)
        if not path.is_file() or path.is_symlink():
            raise ValueError("backup invalido")
        original = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
        try:
            restored = sqlite3.connect(":memory:")
            try:
                original.backup(restored)
                integrity = restored.execute("PRAGMA integrity_check").fetchone()[0]
                if integrity != "ok":
                    raise RuntimeError("restauracao falhou")
                ais_rows = restored.execute("SELECT COUNT(*) FROM maritime_ais").fetchone()[0]
                lineup_rows = restored.execute("SELECT COUNT(*) FROM maritime_lineup").fetchone()[0]
                # Optional versioned-lineup schema, created when the new ledger
                # is used. Legacy databases remain backward compatible.
                has_vintages = restored.execute("""
                    SELECT 1 FROM sqlite_master
                    WHERE type='table' AND name='maritime_lineup_vintages'
                """).fetchone() is not None
                vintage_rows = (
                    restored.execute("SELECT COUNT(*) FROM maritime_lineup_vintages").fetchone()[0]
                    if has_vintages else 0
                )
                return {
                    "integrity": "ok", "ais_rows": ais_rows,
                    "lineup_rows": lineup_rows, "lineup_vintage_rows": vintage_rows,
                }
            finally:
                restored.close()
        finally:
            original.close()
