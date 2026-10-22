#!/usr/bin/env python3
"""NIVON PTAX: pacote portátil para restauracao LOCAL controlada.

Opera apenas em arquivos JSONL PRIVADOS exportados de tres tabelas Neon.
NUNCA faz rede, SQL remoto, backup do banco ativo, deploy, nem upload.
Restaura e valida em SQLite :memory: (ensaio de arquivo, nao PG restore).
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import sqlite3
import sys
from datetime import date
from decimal import Decimal
from pathlib import Path
from typing import Any

from ptax_neon_to_bigquery_jsonl import normalize, parse_date, parse_timestamp

ROOT = Path(__file__).resolve().parents[1]
FILES = {
    "quotes": "nivon_ptax_quotes.jsonl",
    "runs": "nivon_ptax_runs.jsonl",
    "checkpoints": "nivon_ptax_checkpoints.jsonl",
}
FIELDS = {
    "quotes": frozenset((
        "id currency reference_date quote_time_original bulletin_type buy_brl sell_brl "
        "unit source license published_at first_collected_at last_verified_at observation_kind"
    ).split()),
    "runs": frozenset((
        "id job_type currency window_start window_end started_at finished_at "
        "status fetched inserted error_class detail"
    ).split()),
    "checkpoints": frozenset((
        "currency window_start window_end last_completed_at status fetched"
    ).split()),
}
MAX_ROWS = 500_000
MAX_FILE_BYTES = 1_000_000_000


class BackupError(ValueError):
    """Nao imprime precos, SQL, paths ou credenciais."""


def _private_path(path: Path, *, must_exist: bool = True) -> Path:
    if path.is_symlink():
        raise BackupError("symlink proibido no diretorio")
    actual = path.resolve(strict=must_exist)
    if actual.is_relative_to(ROOT):
        raise BackupError("backup nao pode residir no repositorio publico")
    if must_exist and not actual.is_dir():
        raise BackupError("diretorio ausente")
    return actual


def _validated_file(folder: Path, filename: str) -> Path:
    p = folder / filename
    if p.is_symlink() or not p.is_file() or p.stat().st_size > MAX_FILE_BYTES:
        raise BackupError("arquivo ausente, symlink ou excessivo")
    return p


def _text(row: dict[str, Any], name: str) -> str:
    val = row.get(name)
    if not isinstance(val, str) or not val.strip():
        raise BackupError("campo texto ausente/invalido")
    return val


def _positive_id(row: dict[str, Any]) -> int:
    val = row.get("id")
    if isinstance(val, bool) or not isinstance(val, int) or val <= 0:
        raise BackupError("id invalido")
    return val


def _count(row: dict[str, Any], key: str) -> int:
    val = row.get(key)
    if isinstance(val, bool) or not isinstance(val, int) or val < 0:
        raise BackupError("contador invalido")
    return val


def _date_window(row: dict[str, Any]) -> tuple[str, str]:
    a, b = parse_date(row, "window_start"), parse_date(row, "window_end")
    if date.fromisoformat(b) < date.fromisoformat(a):
        raise BackupError("janela temporal invertida")
    return a, b


def _key_for(kind: str, row: dict[str, Any]) -> str:
    if not isinstance(row, dict) or set(row) != FIELDS[kind]:
        raise BackupError("contrato de coluna divergente")
    currency = _text(row, "currency")
    if currency not in ("USD", "EUR"):
        raise BackupError("moeda fora do contrato")
    if kind == "quotes":
        _positive_id(row)
        item = normalize(row)
        return item["quote_id"]
    start, end = _date_window(row)
    if kind == "runs":
        run_id = _positive_id(row)
        if _text(row, "job_type") not in ("DAILY", "BACKFILL", "SMOKE"):
            raise BackupError("job_type invalido")
        if _text(row, "status") not in ("RUNNING", "SUCCESS", "EMPTY", "ERROR"):
            raise BackupError("status invalido")
        parse_timestamp(row, "started_at")
        parse_timestamp(row, "finished_at", nullable=True)
        _count(row, "fetched")
        _count(row, "inserted")
        for k in ("error_class", "detail"):
            if row[k] is not None and not isinstance(row[k], str):
                raise BackupError("campo opcional invalido")
        return str(run_id)
    if _text(row, "status") not in ("SUCCESS", "EMPTY"):
        raise BackupError("status checkpoint invalido")
    parse_timestamp(row, "last_completed_at")
    _count(row, "fetched")
    return json.dumps([currency, start, end], separators=(",", ":"))


def _sha_file(path: Path) -> tuple[str, int]:
    sha = hashlib.sha256()
    total = 0
    with path.open("rb") as fp:
        while True:
            piece = fp.read(1 << 20)
            if not piece:
                break
            sha.update(piece)
            total += len(piece)
            if total > MAX_FILE_BYTES:
                raise BackupError("arquivo acima do limite")
    return sha.hexdigest(), total


def _replay(folder: Path) -> dict[str, Any]:
    db = sqlite3.connect(":memory:")
    db.execute("CREATE TABLE archive (table_name TEXT NOT NULL, row_key TEXT NOT NULL,"
               " row_bytes BLOB NOT NULL, PRIMARY KEY(table_name,row_key)) WITHOUT ROWID")
    stats: dict[str, Any] = {}
    try:
        for kind, fname in FILES.items():
            path = _validated_file(folder, fname)
            digest, size = _sha_file(path)
            count = 0
            with path.open("rb") as fp:
                for raw in fp:
                    count += 1
                    if count > MAX_ROWS or not raw.endswith(b"\n") or len(raw) > 1_000_000:
                        raise BackupError("registro truncado ou quantidade excessiva")
                    try:
                        row = json.loads(raw.decode("utf-8"), parse_float=Decimal)
                        key = _key_for(kind, row)
                    except (UnicodeError, TypeError, ValueError, KeyError):
                        raise BackupError("registro invalido no pacote") from None
                    try:
                        db.execute("INSERT INTO archive VALUES(?,?,?)", (kind, key, raw))
                    except sqlite3.IntegrityError:
                        raise BackupError("chave duplicada no arquivo")
            restored = db.execute(
                "SELECT COUNT(*) FROM archive WHERE table_name=?", (kind,)
            ).fetchone()[0]
            if restored != count:
                raise BackupError("replay nao restituiu todos os registros")
            # Round-trip por chave, sem carregar os arquivos inteiros na memoria.
            with path.open("rb") as fp:
                for raw in fp:
                    try:
                        obj = json.loads(raw.decode("utf-8"), parse_float=Decimal)
                        key = _key_for(kind, obj)
                    except (UnicodeError, TypeError, ValueError, KeyError):
                        raise BackupError("registro invalido na releitura") from None
                    restored = db.execute(
                        "SELECT row_bytes FROM archive WHERE table_name=? AND row_key=?",
                        (kind, key),
                    ).fetchone()
                    if restored is None or restored[0] != raw:
                        raise BackupError("replay divergiu dos registros do arquivo")
            stats[kind] = {"sha256": digest, "bytes": size, "rows": count}
        if stats["quotes"]["rows"] == 0:
            raise BackupError("backup sem nenhuma cotacao")
        return stats
    finally:
        db.close()


def build(input_dir: Path, bundle_dir: Path) -> dict[str, Any]:
    source = _private_path(input_dir)
    destination = _private_path(bundle_dir, must_exist=False)
    if destination.exists() or destination.is_relative_to(source):
        raise BackupError("destino existente ou interno a origem")
    stats = _replay(source)
    destination.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    destination.mkdir(mode=0o700)
    try:
        for kind, filename in FILES.items():
            src = _validated_file(source, filename)
            dest = destination / filename
            fd = os.open(dest, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            with src.open("rb") as inp, os.fdopen(fd, "wb") as out:
                shutil.copyfileobj(inp, out, length=1 << 20)
        if _replay(destination) != stats:
            raise BackupError("copia ou replay divergente")
        manifest = {
            "schema_version": "1.0.0",
            "source": "NIVON_NEON_PTAX_PRIVATE_EXPORT",
            "files": {FILES[k]: stats[k] for k in FILES},
            "snapshot_consistency_verified": False,
            "origin_neon_reconciled": False,
            "independent_storage_verified": False,
            "postgres_native_restore_verified": False,
            "cloud_migration_completed": False,
            "cutover_allowed": False,
        }
        payload = (json.dumps(manifest, sort_keys=True, indent=2) + "\n").encode("utf-8")
        fd = os.open(destination / "manifest.json", os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, "wb") as out:
            out.write(payload)
        return verify(destination)
    except BaseException:
        shutil.rmtree(destination)
        raise


def verify(bundle_dir: Path) -> dict[str, Any]:
    folder = _private_path(bundle_dir)
    if {x.name for x in folder.iterdir()} != set(FILES.values()) | {"manifest.json"}:
        raise BackupError("estrutura inesperada do pacote")
    mp = _validated_file(folder, "manifest.json")
    if mp.stat().st_size > 100_000:
        raise BackupError("manifesto excessivo")
    try:
        manifest = json.loads(mp.read_text(encoding="utf-8"))
    except (ValueError, UnicodeError):
        raise BackupError("manifesto ilegivel") from None
    if (not isinstance(manifest, dict) or manifest.get("schema_version") != "1.0.0"
        or manifest.get("source") != "NIVON_NEON_PTAX_PRIVATE_EXPORT"
        or not isinstance(manifest.get("files"), dict)
        or set(manifest["files"]) != set(FILES.values())):
        raise BackupError("manifesto estruturalmente invalido")
    if any(manifest.get(k) is not False for k in (
        "snapshot_consistency_verified", "origin_neon_reconciled",
        "independent_storage_verified", "postgres_native_restore_verified",
        "cloud_migration_completed", "cutover_allowed"
    )):
        raise BackupError("manifesto com claims prematuros")
    stats = _replay(folder)
    if {FILES[k]: stats[k] for k in FILES} != manifest["files"]:
        raise BackupError("integridade do pacote nao confere com manifesto")
    return {
        "status": "LOCAL_BUNDLE_REPLAY_VERIFIED",
        "table_counts": {k: stats[k]["rows"] for k in FILES},
        "archive_sha256": hashlib.sha256(mp.read_bytes()).hexdigest(),
        "sqlite_memory_replay_verified": True,
        "snapshot_consistency_verified": False,
        "origin_neon_reconciled": False,
        "independent_storage_verified": False,
        "postgres_native_restore_verified": False,
        "cloud_migration_completed": False,
        "cutover_allowed": False,
    }


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Pacote PTAX local verificavel, sem rede.")
    p.add_argument("--build", action="store_true")
    p.add_argument("--verify", action="store_true")
    p.add_argument("--source", type=Path)
    p.add_argument("--bundle", type=Path, required=True)
    a = p.parse_args(argv)
    if a.build == a.verify or (a.build and not a.source):
        p.error("especifique --build --source DIR ou --verify")
    try:
        report = build(a.source, a.bundle) if a.build else verify(a.bundle)
    except (BackupError, OSError, UnicodeError, ValueError, sqlite3.Error):
        print("PTAX_BACKUP_BLOCKED: confira arquivos locais, estrutura, validade e checksums.",
              file=sys.stderr)
        return 3
    print(json.dumps(report, sort_keys=True, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
