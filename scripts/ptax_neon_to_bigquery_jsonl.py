#!/usr/bin/env python3
"""Transforma export local Neon PTAX em JSONL para BigQuery, SEM rede e SEM upload.

Entrada: JSONL de SELECT * FROM public.nivon_ptax_quotes em local PRIVADO.
Saida: arquivo novo, privado (0600), fora do Git, com contagem/hash no stdout.
Nao compara SQL, nao acessa Neon, nao executa bq, nao cria Cloud Storage.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
from datetime import date, datetime, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any, Iterable

ROOT = Path(__file__).resolve().parents[1]
SOURCE_FIELDS = frozenset({
    "id", "currency", "reference_date", "quote_time_original", "bulletin_type",
    "buy_brl", "sell_brl", "unit", "source", "license", "published_at",
    "first_collected_at", "last_verified_at", "observation_kind",
})
REQUIRED = SOURCE_FIELDS - {"id", "published_at"}


class InvalidQuote(ValueError):
    """Inconsistencia de contrato; nao incluir valores do dado em mensagens."""


def require_text(row: dict[str, Any], key: str) -> str:
    value = row.get(key)
    if not isinstance(value, str) or not value.strip():
        raise InvalidQuote(f"campo obrigatorio ausente/invalido: {key}")
    return value


def parse_date(row: dict[str, Any], key: str) -> str:
    raw = require_text(row, key)
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", raw):
        raise InvalidQuote(f"data em formato inesperado: {key}")
    try:
        return date.fromisoformat(raw).isoformat()
    except ValueError:
        raise InvalidQuote(f"data invalida: {key}") from None


def parse_timestamp(row: dict[str, Any], key: str, nullable: bool = False) -> str | None:
    raw = row.get(key)
    if raw is None and nullable:
        return None
    if not isinstance(raw, str) or not raw.strip():
        raise InvalidQuote(f"timestamp ausente/invalido: {key}")
    try:
        parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        raise InvalidQuote(f"timestamp em formato invalido: {key}") from None
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise InvalidQuote(f"timestamp sem offset: {key}")
    return parsed.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def parse_decimal(row: dict[str, Any], key: str) -> str:
    value = row.get(key)
    if not isinstance(value, (str, int, Decimal)) or isinstance(value, bool):
        raise InvalidQuote(f"decimal ausente/invalido: {key}")
    try:
        number = Decimal(str(value))
    except InvalidOperation:
        raise InvalidQuote(f"decimal invalido: {key}") from None
    if not number.is_finite() or number <= 0:
        raise InvalidQuote(f"decimal nao positivo/finito: {key}")
    sign, digits, exponent = number.as_tuple()
    fraction = max(-exponent, 0)
    integer = max(len(digits) + exponent, 0)
    # Coluna origem PostgreSQL NUMERIC(18,9): ate 9 digitos inteiros e 9 decimais.
    if integer > 9 or fraction > 9:
        raise InvalidQuote(f"decimal fora do esquema Neon: {key}")
    return format(number.normalize(), "f")


def normalize(row: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(row, dict):
        raise InvalidQuote("linha nao e objeto JSON")
    unknown = row.keys() - SOURCE_FIELDS
    missing = REQUIRED - row.keys()
    if unknown or missing:
        raise InvalidQuote("campos ausentes ou nao esperados no contrato PTAX")
    currency = require_text(row, "currency")
    if currency not in ("USD", "EUR"):
        raise InvalidQuote("moeda invalida")
    reference = parse_date(row, "reference_date")
    quote_time = require_text(row, "quote_time_original")
    bulletin = require_text(row, "bulletin_type")
    buy, sell = parse_decimal(row, "buy_brl"), parse_decimal(row, "sell_brl")
    unit, source = require_text(row, "unit"), require_text(row, "source")
    license_text, kind = require_text(row, "license"), require_text(row, "observation_kind")
    if kind != "INFORMADO":
        raise InvalidQuote("natureza PTAX inesperada")
    published = parse_timestamp(row, "published_at", nullable=True)
    first = parse_timestamp(row, "first_collected_at")
    last = parse_timestamp(row, "last_verified_at")
    if datetime.fromisoformat(last.replace("Z", "+00:00")) < datetime.fromisoformat(first.replace("Z", "+00:00")):
        raise InvalidQuote("ultima verificacao anterior a primeira coleta")
    source_id = row.get("id")
    if source_id is not None and (isinstance(source_id, bool) or
                                  not isinstance(source_id, int) or source_id <= 0):
        raise InvalidQuote("id fonte invalido")

    key = [currency, reference, quote_time, bulletin, buy, sell]
    quote_id = hashlib.sha256(
        json.dumps(key, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    canonical_source = {
        "id": source_id,
        "currency": currency,
        "reference_date": reference,
        "quote_time_original": quote_time,
        "bulletin_type": bulletin,
        "buy_brl": buy,
        "sell_brl": sell,
        "unit": unit,
        "source": source,
        "license": license_text,
        "published_at": published,
        "first_collected_at": first,
        "last_verified_at": last,
        "observation_kind": kind,
    }
    record_sha = hashlib.sha256(
        json.dumps(canonical_source, ensure_ascii=False,
                   sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    return {
        "quote_id": quote_id, "currency": currency, "reference_date": reference,
        "quote_time_original": quote_time, "bulletin_type": bulletin,
        "buy_brl": buy, "sell_brl": sell, "unit": unit, "source": source,
        "license": license_text, "published_at": published,
        "first_collected_at": first, "last_verified_at": last,
        "observation_kind": kind, "record_sha256": record_sha,
        "origem_sha256": None,  # payload OData original NAO disponivel no Neon.
        "vintage_id": quote_id, "source_neon_row_id": source_id,
        "migration_schema_version": "1.0.0",
        "quality_status": "NEON_EXPORT_UNVERIFIED",
    }


def convert(input_file: Path, output_file: Path) -> dict[str, Any]:
    input_file = input_file.resolve()
    output_file = output_file.resolve()
    if input_file == output_file or input_file.is_relative_to(ROOT) or output_file.is_relative_to(ROOT):
        raise InvalidQuote("entrada e saida devem estar fora do repositorio publico")
    if output_file.exists():
        raise InvalidQuote("arquivo de saida ja existe: nao sobrescrever")
    if not input_file.is_file():
        raise InvalidQuote("arquivo de entrada ausente")
    output_file.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    fd = os.open(output_file, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    counts: dict[str, int] = {"USD": 0, "EUR": 0}
    ranges: dict[str, list[str | None]] = {"USD": [None, None], "EUR": [None, None]}
    ids: set[str] = set()
    sha = hashlib.sha256()
    try:
        with input_file.open("r", encoding="utf-8") as source, os.fdopen(fd, "w", encoding="utf-8", newline="\n") as target:
            for index, line in enumerate(source, 1):
                if not line.strip():
                    raise InvalidQuote(f"linha {index}: linha vazia")
                try:
                    row = json.loads(line, parse_float=Decimal)
                    mapped = normalize(row)
                except (ValueError, TypeError) as exc:
                    raise InvalidQuote(f"linha {index}: estrutura/valor invalido") from None
                if mapped["quote_id"] in ids:
                    raise InvalidQuote(f"linha {index}: cotacao duplicada")
                ids.add(mapped["quote_id"])
                content = (json.dumps(mapped, ensure_ascii=False, separators=(",", ":")) + "\n").encode("utf-8")
                target.write(content.decode("utf-8"))
                sha.update(content)
                currency, dt = mapped["currency"], mapped["reference_date"]
                counts[currency] += 1
                if ranges[currency][0] is None or dt < ranges[currency][0]:
                    ranges[currency][0] = dt
                if ranges[currency][1] is None or dt > ranges[currency][1]:
                    ranges[currency][1] = dt
        return {
            "schema_version": "1.0.0", "status": "LOCAL_EXPORT_UNVERIFIED",
            "quote_count": sum(counts.values()), "count_by_currency": counts,
            "range_by_currency": ranges, "output_sha256": sha.hexdigest(),
            "uploaded_to_cloud": False, "export_reconciled_against_neon": False,
            "raw_odata_checksum_available": False,
        }
    except BaseException:
        output_file.unlink(missing_ok=True)
        raise


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Migracao PTAX: transformacao local sem cloud e sem rede.")
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        report = convert(args.input, args.output)
    except (InvalidQuote, OSError, UnicodeError) as exc:
        print(f"EXPORT BLOQUEADO: {type(exc).__name__}. Confira entrada, permissao e contrato.", file=sys.stderr)
        return 3
    print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
