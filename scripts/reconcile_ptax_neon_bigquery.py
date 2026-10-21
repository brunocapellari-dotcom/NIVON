#!/usr/bin/env python3
"""Concilia dois snapshots privados JSONL PTAX: Neon raw e BigQuery exportado.

Somente leitura, sem rede/SQL/GCP, sem exibir precos, chaves de linha ou caminhos.
Uma igualdade local NAO autoriza desligar Neon, nem prova backup ou restore.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from collections import Counter
from decimal import Decimal
from pathlib import Path
from typing import Any

from ptax_neon_to_bigquery_jsonl import InvalidQuote, normalize, parse_decimal, parse_timestamp

ROOT = Path(__file__).resolve().parents[1]
TARGET_FIELDS = frozenset({
    "quote_id", "currency", "reference_date", "quote_time_original", "bulletin_type",
    "buy_brl", "sell_brl", "unit", "source", "license", "published_at",
    "first_collected_at", "last_verified_at", "observation_kind", "record_sha256",
    "origem_sha256", "vintage_id", "source_neon_row_id", "migration_schema_version",
    "quality_status",
})
MAX_RECORDS = 500_000


class InvalidSnapshot(ValueError):
    """Erro de estrutura sem conter detalhes dos dados."""


def _bq_timestamp(value: Any, *, nullable: bool = False) -> str | None:
    if nullable and value is None:
        return None
    if not isinstance(value, str):
        raise InvalidSnapshot("timestamp invalido")
    # Export do BigQuery pode usar sufixo ' UTC'. Nunca inventar timezone.
    cleaned = value[:-4] + "+00:00" if value.endswith(" UTC") else value
    return parse_timestamp({"ts": cleaned}, "ts", nullable=nullable)


def canonical_target(row: Any) -> dict[str, Any]:
    """Converte BQ exportado ao contrato canonico sem confiar nos hashes declarados."""
    if not isinstance(row, dict) or set(row) != TARGET_FIELDS:
        raise InvalidSnapshot("contrato de colunas do destino invalido")
    src_id = row["source_neon_row_id"]
    if src_id is not None:
        if isinstance(src_id, bool):
            raise InvalidSnapshot("identificador de origem invalido")
        if isinstance(src_id, str) and src_id.isdecimal() and str(int(src_id)) == src_id:
            src_id = int(src_id)
        elif not isinstance(src_id, int):
            raise InvalidSnapshot("identificador de origem invalido")
    source = {
        "id": src_id,
        "currency": row["currency"],
        "reference_date": row["reference_date"],
        "quote_time_original": row["quote_time_original"],
        "bulletin_type": row["bulletin_type"],
        "buy_brl": parse_decimal(row, "buy_brl"),
        "sell_brl": parse_decimal(row, "sell_brl"),
        "unit": row["unit"],
        "source": row["source"],
        "license": row["license"],
        "published_at": _bq_timestamp(row["published_at"], nullable=True),
        "first_collected_at": _bq_timestamp(row["first_collected_at"]),
        "last_verified_at": _bq_timestamp(row["last_verified_at"]),
        "observation_kind": row["observation_kind"],
    }
    expected = normalize(source)
    for key in (
        "quote_id", "record_sha256", "vintage_id", "origem_sha256",
        "migration_schema_version", "quality_status",
    ):
        if row[key] != expected[key]:
            raise InvalidSnapshot("metadados ou hash inconsistentes no destino")
    return expected


def _private_file(path: Path) -> Path:
    resolved = path.resolve(strict=True)
    if not resolved.is_file() or resolved.is_relative_to(ROOT):
        raise InvalidSnapshot("arquivo inexistente ou no repositorio publico")
    return resolved


def _load(path: Path, role: str) -> tuple[dict[str, dict[str, Any]], int, int, str, Counter[str]]:
    rows: dict[str, dict[str, Any]] = {}
    duplicate_count = 0
    total = 0
    digest = hashlib.sha256()
    currencies: Counter[str] = Counter()
    with path.open("rb") as file:
        for raw in file:
            total += 1
            if total > MAX_RECORDS:
                raise InvalidSnapshot("export muito grande: separar por janelas")
            digest.update(raw)
            try:
                obj = json.loads(raw.decode("utf-8"), parse_float=Decimal)
                item = normalize(obj) if role == "neon" else canonical_target(obj)
            except (UnicodeError, ValueError, TypeError, KeyError, InvalidQuote):
                raise InvalidSnapshot(f"linha {total}: formato invalido no snapshot {role}") from None
            key = item["quote_id"]
            if key in rows:
                duplicate_count += 1
            else:
                rows[key] = item
            currencies[item["currency"]] += 1
    return rows, total, duplicate_count, digest.hexdigest(), currencies


def reconcile(source_file: Path, target_file: Path) -> dict[str, Any]:
    source, target = _private_file(source_file), _private_file(target_file)
    if source.samefile(target):
        raise InvalidSnapshot("origem e destino sao o mesmo arquivo")
    src, ns, ds, hs, sc = _load(source, "neon")
    dst, nt, dt, ht, tc = _load(target, "bigquery")
    common = src.keys() & dst.keys()
    modified = sum(1 for key in common if src[key] != dst[key])
    absent = len(src.keys() - dst.keys())
    extra = len(dst.keys() - src.keys())
    matched = sum(1 for key in common if src[key] == dst[key])
    consistent = bool(ns > 0 and nt > 0 and ns == nt and not any((ds, dt, modified, absent, extra)))
    return {
        "schema_version": "1.0.0",
        "source_records": ns, "target_records": nt,
        "source_unique_keys": len(src), "target_unique_keys": len(dst),
        "source_duplicate_keys": ds, "target_duplicate_keys": dt,
        "source_currency_counts": {k: sc[k] for k in ("USD", "EUR")},
        "target_currency_counts": {k: tc[k] for k in ("USD", "EUR")},
        "matching_records": matched,
        "missing_in_target": absent, "unexpected_in_target": extra,
        "changed_records": modified,
        "source_file_sha256": hs, "target_file_sha256": ht,
        "local_snapshot_consistent": consistent,
        "status": "CONSISTENT_LOCAL_SNAPSHOTS" if consistent else "BLOCKED_RECONCILIATION_MISMATCH",
        "cutover_approved": False,
        "backup_restore_verified": False,
        "cloud_project_access_verified": False,
        "neon_trigger_changed": False,
        "next_gate": (
            "REPEAT_WITH_CONTROLLED_EXPORT_AND_INDEPENDENT_BACKUP_RESTORE"
            if consistent else "REPAIR_EXPORT_AND_RESNAPSHOT"
        ),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Conciliação PTAX offline sem acessar bancos ou rede.")
    parser.add_argument("--source-neon", required=True, type=Path)
    parser.add_argument("--target-bigquery", required=True, type=Path)
    args = parser.parse_args(argv)
    try:
        result = reconcile(args.source_neon, args.target_bigquery)
    except (OSError, InvalidSnapshot, InvalidQuote, UnicodeError):
        print("RECONCILIATION_BLOCKED: arquivo ou contrato invalido. Nada foi modificado.", file=sys.stderr)
        return 3
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
    return 0 if result["local_snapshot_consistent"] else 4


if __name__ == "__main__":
    raise SystemExit(main())
