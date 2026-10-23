#!/usr/bin/env python3
"""Validacao fail-closed do manifesto agregado PTAX, sem acesso a Neon ou GCP.

Entrada e saida so contem metadados agregados; nenhuma cotacao individual.
Um manifesto coerente NAO comprova origem independente, backup ou completude.
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import date, datetime
from pathlib import Path
from typing import Any

CONTRACT = "NIVON_PTAX_SOURCE_AUDIT_V1"
MAX_INPUT_BYTES = 1_000_000


class ManifestError(ValueError):
    pass


def _integer(item: dict[str, Any], name: str) -> int:
    val = item.get(name)
    if isinstance(val, bool) or not isinstance(val, int) or val < 0:
        raise ManifestError(f"contagem ausente/invalida: {name}")
    return val


def _date_iso(value: Any) -> date:
    if not isinstance(value, str):
        raise ManifestError("data de referencia ausente")
    try:
        parsed = date.fromisoformat(value)
    except ValueError:
        raise ManifestError("data de referencia invalida") from None
    if parsed.isoformat() != value:
        raise ManifestError("data de referencia nao canonica")
    return parsed


def analyze(value: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ManifestError("manifesto nao e objeto")
    if "source_audit_manifest" in value:
        if set(value) != {"source_audit_manifest"}:
            raise ManifestError("envelope invalido")
        value = value["source_audit_manifest"]
    if not isinstance(value, dict) or value.get("contract") != CONTRACT:
        raise ManifestError("contrato de origem incorreto")
    if value.get("source") != "Neon NIVON-PTAX-OPERACIONAL/public.nivon_ptax_quotes":
        raise ManifestError("fonte nao homologada")
    ts = value.get("snapshot_timestamp_utc")
    if not isinstance(ts, str) or not ts.endswith("Z"):
        raise ManifestError("timestamp do relatorio ausente")
    try:
        datetime.fromisoformat(ts.replace("Z", "+00:00"))
    except ValueError:
        raise ManifestError("timestamp do relatorio invalido") from None

    num_fields = (
        "quote_count", "run_count", "run_errors", "run_running",
        "run_successful", "checkpoint_count", "invalid_timestamps",
        "invalid_currency", "invalid_prices", "suspect_publication",
        "duplicate_business_keys",
    )
    nums = {key: _integer(value, key) for key in num_fields}
    if nums["run_successful"] + nums["run_errors"] + nums["run_running"] > nums["run_count"]:
        raise ManifestError("status de execucoes maior que total")
    # Um run pode materializar multiplos checkpoints; nao presumir 1:1.

    by_currency = value.get("by_currency")
    by_year = value.get("by_year")
    if not isinstance(by_currency, list) or not isinstance(by_year, list):
        raise ManifestError("distribuicoes por moeda/ano ausentes")
    totals: dict[str, tuple[int, int, int, int]] = {}
    for item in by_currency:
        if not isinstance(item, dict):
            raise ManifestError("moeda malformada")
        currency = item.get("currency")
        if currency not in ("USD", "EUR") or currency in totals:
            raise ManifestError("moeda duplicada ou desconhecida")
        n = _integer(item, "quotes")
        nd = _integer(item, "reference_days")
        first = _date_iso(item.get("first_reference"))
        last = _date_iso(item.get("last_reference"))
        if n == 0 or nd == 0 or nd > n or first > last:
            raise ManifestError("contagem/intervalo invalido por moeda")
        if not isinstance(item.get("last_verified"), str):
            raise ManifestError("sem data de verificacao")
        totals[currency] = (n, nd, first.year, last.year)
    if set(totals) != {"USD", "EUR"} or sum(v[0] for v in totals.values()) != nums["quote_count"]:
        raise ManifestError("contagens por moeda divergentes")

    by_ccy_year: dict[tuple[str, int], tuple[int, int]] = {}
    for item in by_year:
        if not isinstance(item, dict):
            raise ManifestError("ano malformado")
        currency, year = item.get("currency"), item.get("year")
        if currency not in totals or isinstance(year, bool) or not isinstance(year, int) or not (1900 <= year <= 2100):
            raise ManifestError("ano/moeda invalido")
        key = (currency, year)
        if key in by_ccy_year:
            raise ManifestError("ano/moeda duplicado")
        n, d = _integer(item, "quotes"), _integer(item, "reference_days")
        if n == 0 or d == 0 or d > n or not (totals[currency][2] <= year <= totals[currency][3]):
            raise ManifestError("contagem por ano invalida")
        by_ccy_year[key] = (n, d)
    for currency, (n, days, ymin, ymax) in totals.items():
        rows = [numbers for (cur, year), numbers in by_ccy_year.items() if cur == currency]
        if sum(x for x, _ in rows) != n or sum(y for _, y in rows) != days:
            raise ManifestError("somas anuais divergentes")

    anomalies = sum(nums[key] for key in (
        "invalid_timestamps", "invalid_currency", "invalid_prices",
        "suspect_publication", "duplicate_business_keys",
    ))
    missing_years = {
        c: [y for y in range(totals[c][2], totals[c][3]+1) if (c, y) not in by_ccy_year]
        for c in ("USD", "EUR")
    }
    if any(value.get(key) is not False for key in (
        "origin_coverage_complete", "external_backup_restored",
        "bigquery_migrated", "migration_authorized",
    )):
        raise ManifestError("o relatorio nao pode afirmar que gates externos foram concluídos")
    return {
        "contract": CONTRACT,
        "snapshot_timestamp_utc": ts,
        "quotes": nums["quote_count"],
        "currency_quotes": {c: totals[c][0] for c in ("USD", "EUR")},
        "currency_reference_days": {c: totals[c][1] for c in ("USD", "EUR")},
        "missing_intermediate_years": missing_years,
        "anomaly_count": anomalies,
        "run_errors": nums["run_errors"],
        "basic_source_integrity_passed": bool(nums["quote_count"] and anomalies == 0 and nums["run_errors"] == 0),
        "historical_coverage_verified": False,
        "external_backup_restore_verified": False,
        "bigquery_data_verified": False,
        "migration_or_cutover_approved": False,
        "recommendation": (
            "SOURCE_REPAIR_REQUIRED" if anomalies else
            "BACKFILL_AND_BACKUP_REQUIRED" if any(missing_years.values()) else
            "INDEPENDENT_COVERAGE_AND_BACKUP_VALIDATION_REQUIRED"
        ),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Analisa manifest PTAX agregado da SQL read-only.")
    parser.add_argument("--input", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        if args.input.stat().st_size > MAX_INPUT_BYTES:
            raise ManifestError("arquivo excessivo")
        raw = json.loads(args.input.read_text(encoding="utf-8"))
        result = analyze(raw)
    except (OSError, UnicodeError, ValueError, TypeError):
        print("SOURCE_MANIFEST_INVALID_OR_UNREADABLE", file=sys.stderr)
        return 3
    print(json.dumps(result, indent=2, sort_keys=True, ensure_ascii=False))
    return 0 if result["basic_source_integrity_passed"] else 4


if __name__ == "__main__":
    raise SystemExit(main())
