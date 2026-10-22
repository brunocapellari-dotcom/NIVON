#!/usr/bin/env python3
"""Valida manifesto agregado do backfill PTAX, sem ligar ao banco ou agendador.

O resultado NAO comprova completude de datas de cotacao, backup ou BigQuery.
Entrada: JSON serializado da consulta database/neon_ptax_backfill_health.sql.
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any

START = date(2020, 1, 1)
WINDOW_DAYS = 31
LIMIT = 1_000_000


class HealthInvalid(ValueError):
    """Falha de contrato, sem imprimir dados da origem."""


def _int(row: dict[str, Any], key: str) -> int:
    value = row.get(key)
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise HealthInvalid("contador invalido: " + key)
    return value


def _date(value: Any, *, optional: bool = False) -> date | None:
    if optional and value is None:
        return None
    if not isinstance(value, str):
        raise HealthInvalid("data ausente")
    try:
        d = date.fromisoformat(value)
    except ValueError:
        raise HealthInvalid("data invalida") from None
    if d.isoformat() != value:
        raise HealthInvalid("data nao canonica")
    return d


def _timestamp(value: Any, *, optional: bool = False) -> datetime | None:
    if optional and value is None:
        return None
    if not isinstance(value, str):
        raise HealthInvalid("timestamp ausente")
    try:
        ts = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        raise HealthInvalid("timestamp invalido") from None
    if ts.utcoffset() is None:
        raise HealthInvalid("timestamp sem timezone")
    return ts


def analyze(raw: Any) -> dict[str, Any]:
    if not isinstance(raw, dict):
        raise HealthInvalid("manifesto ausente")
    if "backfill_health" in raw:
        if set(raw) != {"backfill_health"}:
            raise HealthInvalid("envelope inesperado")
        raw = raw["backfill_health"]
    if not isinstance(raw, dict):
        raise HealthInvalid("manifesto malformado")
    if raw.get("contract") != "NIVON_PTAX_BACKFILL_HEALTH_V1":
        raise HealthInvalid("contrato nao reconhecido")
    if raw.get("status") != "OBSERVED_CHECKPOINTS_NOT_FULL_SOURCE_COVERAGE":
        raise HealthInvalid("estado da auditoria inesperado")
    if raw.get("historical_start") != START.isoformat() or raw.get("nominal_window_days") != WINDOW_DAYS:
        raise HealthInvalid("horizonte de backfill inesperado")
    as_of = _date(raw.get("as_of_sao_paulo_date"))
    observed = _timestamp(raw.get("observed_at_utc"))
    if not raw["observed_at_utc"].endswith("Z"):
        raise HealthInvalid("instante nao UTC")
    if as_of < START or as_of > observed.date() + timedelta(days=1):
        raise HealthInvalid("as_of fora do instante verificado")
    for key in ("external_backup_verified", "bigquery_loaded", "cutover_approved"):
        if raw.get(key) is not False:
            raise HealthInvalid("gate indevidamente liberado")
    rows = raw.get("by_currency")
    if not isinstance(rows, list) or len(rows) != 2:
        raise HealthInvalid("duas moedas obrigatorias")

    expected_count = (as_of - START).days // WINDOW_DAYS + 1
    result = []
    seen: set[str] = set()
    for row in rows:
        if not isinstance(row, dict):
            raise HealthInvalid("moeda malformada")
        c = row.get("currency")
        if c not in ("USD", "EUR") or c in seen:
            raise HealthInvalid("moeda ausente ou duplicada")
        seen.add(c)
        count_fields = (
            "expected_windows", "completed_windows", "pending_windows",
            "non_historical_checkpoints", "backfill_fetched", "backfill_errors",
            "daily_errors", "stored_quotes", "stored_reference_dates",
        )
        values = {field: _int(row, field) for field in count_fields}
        if values["expected_windows"] != expected_count:
            raise HealthInvalid("planejamento temporal divergente")
        if values["completed_windows"] + values["pending_windows"] != expected_count:
            raise HealthInvalid("estado de janelas inconsistente")
        if values["stored_reference_dates"] > values["stored_quotes"]:
            raise HealthInvalid("contagem de datas maior que cotacoes")
        if row.get("historical_source_coverage_verified") is not False:
            raise HealthInvalid("fonte declarada completa sem prova")
        if row.get("gcp_migration_authorized") is not False:
            raise HealthInvalid("migracao autorizada indevidamente")

        nxt = _date(row.get("next_pending_start"), optional=True)
        end = _date(row.get("next_pending_end"), optional=True)
        contiguous = _date(row.get("contiguous_completed_through"))
        farthest = _date(row.get("farthest_completed_end"), optional=True)
        newest = _date(row.get("newest_observed_date"), optional=True)
        last_checkpoint = _timestamp(row.get("last_checkpoint"), optional=True)
        last_backfill = _timestamp(row.get("last_backfill_run"), optional=True)
        last_daily = _timestamp(row.get("last_daily_run"), optional=True)

        if values["pending_windows"]:
            if nxt is None or end is None or end != min(nxt + timedelta(days=30), as_of):
                raise HealthInvalid("janela pendente invalida")
            offset = (nxt - START).days
            if offset < 0 or offset % WINDOW_DAYS:
                raise HealthInvalid("inicio pendente fora da grade")
            if contiguous != nxt - timedelta(days=1):
                raise HealthInvalid("watermark contiguo incorreto")
        else:
            if nxt is not None or end is not None or contiguous != as_of:
                raise HealthInvalid("sem pendencias mas com watermark invalido")
        if values["completed_windows"] == 0:
            if farthest is not None or last_backfill is not None:
                raise HealthInvalid("falso progresso no backfill")
        elif farthest is None or last_backfill is None:
            raise HealthInvalid("backfill sem evidencia temporal")
        if farthest is not None and (farthest < START or farthest > as_of):
            raise HealthInvalid("checkpoint fora do intervalo")
        if newest is not None and (newest > as_of or newest < START):
            raise HealthInvalid("data observada fora do horizonte")

        warnings = []
        if values["pending_windows"]:
            warnings.append("HISTORICAL_WINDOWS_PENDING")
        if farthest is not None and farthest > contiguous:
            warnings.append("OUT_OF_ORDER_COMPLETED_WINDOWS")
        if values["backfill_errors"] or values["daily_errors"]:
            warnings.append("COLLECTOR_REPORTED_ERRORS")
        if last_backfill is None:
            warnings.append("NO_SUCCESSFUL_BACKFILL")
        elif (observed - last_backfill).total_seconds() > 3 * 3600:
            warnings.append("BACKFILL_LAST_RUN_OLDER_THAN_3H")
        if last_daily is None:
            warnings.append("NO_SUCCESSFUL_DAILY_RUN")
        # Sem calendário de feriados não derivar "preço do dia atualizado" daqui.
        result.append({
            "currency": c,
            "completed_windows": values["completed_windows"],
            "pending_windows": values["pending_windows"],
            "planned_windows": expected_count,
            "window_progress_pct": round(values["completed_windows"] * 100 / expected_count, 1),
            "continuous_backfill_through": contiguous.isoformat(),
            "next_window": (
                {"start": nxt.isoformat(), "end": end.isoformat()} if nxt is not None else None
            ),
            "stored_quotes": values["stored_quotes"],
            "stored_reference_days": values["stored_reference_dates"],
            "daily_errors": values["daily_errors"],
            "backfill_errors": values["backfill_errors"],
            "other_checkpoints_not_counted_as_history": values["non_historical_checkpoints"],
            "warnings": warnings,
            "source_calendar_completeness_proven": False,
            "backup_restore_proven": False,
            "migration_allowed": False,
        })
    return {
        "contract": "NIVON_PTAX_BACKFILL_VALIDATION_V1",
        "as_of_sao_paulo_date": as_of.isoformat(),
        "observed_at_utc": raw["observed_at_utc"],
        "source": "NEON_PTAX_READONLY_CHECKPOINTS",
        "currencies": sorted(result, key=lambda v: v["currency"]),
        "status": "HISTORICAL_BACKFILL_IN_PROGRESS"
            if any(v["pending_windows"] for v in result)
            else "CHECKPOINTS_COMPLETE_SOURCE_NOT_AUDITED",
        "history_complete": False,
        "live_price_freshness_verified": False,
        "backup_restore_proven": False,
        "gcp_billing_verified": False,
        "cutover_allowed": False,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Validar manifesto agregado de backfill PTAX.")
    parser.add_argument("--input", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        if args.input.stat().st_size > LIMIT:
            raise HealthInvalid("manifesto excessivo")
        result = analyze(json.loads(args.input.read_text(encoding="utf-8")))
    except (OSError, UnicodeError, ValueError, TypeError, KeyError):
        print("NIVON_PTAX_BACKFILL_MANIFEST_INVALID", file=sys.stderr)
        return 3
    print(json.dumps(result, sort_keys=True, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
