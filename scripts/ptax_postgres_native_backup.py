#!/usr/bin/env python3
"""Backup nativo das 3 tabelas NIVON PTAX, sob snapshot pg_dump consistente.

Execução somente EXPLÍCITA, em ambiente com PostgreSQL CLI e PGSERVICE seguro.
Sem tokens, banco de produção como destino, uploads, billing ou escrita remota.
O arquivo é privado, e o restore real permanece PENDENTE.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import stat
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

ROOT = Path(__file__).resolve().parents[1]
TABLES = ("nivon_ptax_quotes", "nivon_ptax_runs", "nivon_ptax_checkpoints")
SEQUENCES = ("nivon_ptax_quotes_id_seq", "nivon_ptax_runs_id_seq")
SCHEMA = "public"
BACKUP_NAME = "nivon_ptax.pgcustom"
MANIFEST_NAME = "manifest.json"
MAX_ARCHIVE_BYTES = 5 * 1024**3
MAX_LIST_BYTES = 512_000


class BackupBlocked(ValueError):
    """Erro sem SQL, path privado, username ou credencial."""


def _dir_path(value: Path, *, must_exist: bool) -> Path:
    if value.is_symlink():
        raise BackupBlocked("symlink em diretorio nao permitido")
    result = value.resolve(strict=must_exist)
    if result.is_relative_to(ROOT):
        raise BackupBlocked("destino sob checkout Git proibido")
    if must_exist and (not result.is_dir() or not result.exists()):
        raise BackupBlocked("diretorio nao encontrado")
    return result


def _hash_file(path: Path) -> tuple[str, int]:
    h = hashlib.sha256()
    size = 0
    with path.open("rb") as fp:
        while True:
            block = fp.read(1024**2)
            if not block:
                break
            size += len(block)
            if size > MAX_ARCHIVE_BYTES:
                raise BackupBlocked("arquivo excessivamente grande")
            h.update(block)
    return h.hexdigest(), size


def _analyze_toc(toc: str) -> dict[str, list[str]]:
    if len(toc.encode("utf-8")) > MAX_LIST_BYTES:
        raise BackupBlocked("TOC grande demais")
    parsed: dict[str, set[str]] = {"TABLE": set(), "TABLE DATA": set(), "SEQUENCE SET": set()}
    # Formato de pg_restore -l: "123; 1259 456 TABLE public nome_table owner".
    expression = re.compile(
        r"^\d+;\s+\d+\s+\d+\s+(TABLE DATA|TABLE|SEQUENCE SET)\s+public\s+([a-z_][a-z0-9_]*)\s+\S+"
    )
    for line in toc.splitlines():
        found = expression.match(line)
        if found:
            category, name = found.groups()
            if name in (SEQUENCES if category == "SEQUENCE SET" else TABLES):
                parsed[category].add(name)
    if any(parsed[category] != set(SEQUENCES if category == "SEQUENCE SET" else TABLES) for category in parsed):
        raise BackupBlocked("tres tabelas e TABLE DATA nao confirmados no arquivo")
    return {k: sorted(v) for k, v in parsed.items()}


def _archive_check(
    archive: Path,
    run: Callable[..., Any] = subprocess.run,
) -> tuple[dict[str, list[str]], str, int]:
    if archive.is_symlink() or not archive.is_file():
        raise BackupBlocked("arquivo nao regular ou ausente")
    sha, bytes_count = _hash_file(archive)
    if bytes_count < 512:
        raise BackupBlocked("arquivo pequeno demais")
    try:
        result = run(
            ["pg_restore", "--list", str(archive)],
            check=False, capture_output=True, text=True, timeout=45,
        )
    except (OSError, subprocess.TimeoutExpired):
        raise BackupBlocked("pg_restore nao confirmou estrutura") from None
    if result.returncode != 0:
        raise BackupBlocked("pg_restore nao conseguiu ler arquivo")
    return _analyze_toc(result.stdout), sha, bytes_count


def build(
    destination: Path,
    *,
    runner: Callable[..., Any] = subprocess.run,
    env: dict[str, str] | None = None,
) -> dict[str, Any]:
    environment = dict(os.environ if env is None else env)
    if not environment.get("PGSERVICE"):
        raise BackupBlocked("PGSERVICE ausente: usar perfil privado autenticado")
    if environment.get("PGPASSWORD"):
        raise BackupBlocked("use .pgpass/PGSERVICE em vez de senha no ambiente")
    if not environment.get("PGSERVICEFILE") and not environment.get("HOME"):
        raise BackupBlocked("servico PG sem arquivo de configuracao ou HOME")
    folder = _dir_path(destination, must_exist=False)
    if folder.exists() or not folder.parent.is_dir():
        raise BackupBlocked("diretorio de destino ja existe ou parent ausente")
    folder.mkdir(mode=0o700)
    archive = folder / BACKUP_NAME
    manifest = folder / MANIFEST_NAME
    try:
        started = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
        command = [
            "pg_dump",
            "--dbname=nivon",
            "--format=custom",
            "--no-owner", "--no-acl",
            "--no-password",
            "--serializable-deferrable",
            "--lock-wait-timeout=5000",
            "--file=" + str(archive),
        ]
        for table in (*TABLES, *SEQUENCES):
            command.append("--table=public." + table)
        try:
            result = runner(
                command, check=False, capture_output=True, text=True,
                timeout=180, env=environment,
            )
        except (OSError, subprocess.TimeoutExpired):
            raise BackupBlocked("pg_dump indisponivel, expirou ou falhou") from None
        if result.returncode != 0:
            raise BackupBlocked("pg_dump nao criou arquivo validado")
        if archive.is_symlink() or not archive.is_file():
            raise BackupBlocked("pg_dump nao produziu arquivo regular")
        os.chmod(archive, 0o600)
        toc, sha, size = _archive_check(archive, run=runner)
        payload = {
            "contract": "NIVON_PTAX_NATIVE_PGDUMP_V1",
            "created_utc": started,
            "archive": BACKUP_NAME,
            "sha256": sha,
            "size_bytes": size,
            "table_of_contents": toc,
            "one_pg_dump_snapshot": True,
            "data_rows_verified": False,
            "source_row_counts_reconciled": False,
            "native_postgres_restore_verified": False,
            "stored_offsite": False,
            "encrypted_archive_verified": False,
            "bigquery_cutover_approved": False,
        }
        # Arquivo de manifesto restrito, nunca no repositório publico.
        fd = os.open(manifest, os.O_CREAT | os.O_WRONLY | os.O_EXCL, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(payload, f, indent=2, sort_keys=True)
            f.write("\n")
        return verify(folder, runner=runner)
    except BaseException:
        shutil.rmtree(folder)
        raise


def verify(
    destination: Path,
    *,
    runner: Callable[..., Any] = subprocess.run,
) -> dict[str, Any]:
    folder = _dir_path(destination, must_exist=True)
    if {p.name for p in folder.iterdir()} != {BACKUP_NAME, MANIFEST_NAME}:
        raise BackupBlocked("pacote incompleto ou com arquivos inesperados")
    manifest_file = folder / MANIFEST_NAME
    if manifest_file.is_symlink() or manifest_file.stat().st_size > 15_000:
        raise BackupBlocked("manifesto ausente, symlink ou excessivo")
    try:
        document = json.loads(manifest_file.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, ValueError):
        raise BackupBlocked("manifesto malformado") from None
    if not isinstance(document, dict) or document.get("contract") != "NIVON_PTAX_NATIVE_PGDUMP_V1":
        raise BackupBlocked("contrato inesperado")
    toc, sha, size = _archive_check(folder / BACKUP_NAME, run=runner)
    if document.get("sha256") != sha or document.get("size_bytes") != size:
        raise BackupBlocked("checksum/tamanho divergente")
    if document.get("archive") != BACKUP_NAME or document.get("table_of_contents") != toc:
        raise BackupBlocked("inventario divergente")
    if document.get("one_pg_dump_snapshot") is not True:
        raise BackupBlocked("proveniencia do snapshot invalida")
    for gate in (
        "data_rows_verified", "source_row_counts_reconciled",
        "native_postgres_restore_verified", "stored_offsite",
        "encrypted_archive_verified", "bigquery_cutover_approved",
    ):
        if document.get(gate) is not False:
            raise BackupBlocked("manifesto com liberacao prematura")
    return {
        "contract": document["contract"],
        "status": "LOCAL_PGDUMP_ARCHIVE_TOC_VERIFIED",
        "archive_sha256": sha,
        "archive_size_bytes": size,
        "tables_confirmed": sorted(TABLES),
        "toc_verified": True,
        "data_rows_verified": False,
        "source_row_counts_reconciled": False,
        "native_postgres_restore_verified": False,
        "stored_offsite": False,
        "encrypted_archive_verified": False,
        "bigquery_cutover_approved": False,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Backup nativo PTAX: apenas quando executado com PGSERVICE privado."
    )
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--build", action="store_true")
    group.add_argument("--verify", action="store_true")
    parser.add_argument("--destination", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        report = build(args.destination) if args.build else verify(args.destination)
    except (BackupBlocked, OSError, UnicodeError, ValueError):
        print("NIVON_PGDUMP_BLOCKED: backup nao confirmado; verificar terminal local e permissao.",
              file=sys.stderr)
        return 3
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
