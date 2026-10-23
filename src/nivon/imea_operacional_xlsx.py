from __future__ import annotations

import hashlib
import json
from collections import Counter
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta
from typing import Any

from .xlsx_legado import read_xlsx

SOURCE_ID = "imea_operational_xlsx"
EXPECTED_SHEETS = {
    "indicadores diarios",
    "indicadores semanais",
    "frete",
    "semeadura",
    "colheita",
}
REGIONS = ("CENTRO-SUL", "MÉDIO-NORTE", "NORDESTE", "NOROESTE", "NORTE", "OESTE", "SUDESTE", "TOTAL MT")


def excel_date(value: Any) -> str:
    if not isinstance(value, (int, float)):
        raise ValueError(f"DATA Excel invalida: {value!r}")
    return (datetime(1899, 12, 30) + timedelta(days=float(value))).date().isoformat()


def normalize_unit(value: Any) -> str | None:
    if value in (None, ""):
        return None
    text = str(value).strip()
    return {"R$/T": "R$/t"}.get(text, text)


def _header(rows: list[list[Any]]) -> tuple[dict[str, int], list[list[Any]]]:
    if not rows:
        raise ValueError("planilha vazia")
    names = [str(value).strip() if value is not None else "" for value in rows[0]]
    return {name: idx for idx, name in enumerate(names)}, rows[1:]


def _get(row: list[Any], idx: dict[str, int], name: str) -> Any:
    pos = idx[name]
    return row[pos] if pos < len(row) else None


def _hash_record(parts: list[Any]) -> str:
    raw = json.dumps(parts, ensure_ascii=False, separators=(",", ":"), default=str).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


@dataclass(frozen=True)
class ImeaRecord:
    record_id: str
    source_id: str
    source_sheet: str
    data_referencia: str
    produto: str
    metric_name: str
    valor: float
    unidade_origem: str | None
    unidade_canonica: str | None
    local: str | None = None
    origem: str | None = None
    destino: str | None = None
    safra: str | None = None
    regiao: str | None = None
    evidence_class: str = "observado"
    evidence_subtype: str = "imea_reference_indicator"
    negotiated: bool = False

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def parse_workbook(payload: bytes) -> dict[str, Any]:
    workbook_sheets = read_xlsx(payload)
    sheets = {sheet.name: sheet.rows for sheet in workbook_sheets}
    if len(sheets) != len(workbook_sheets):
        raise ValueError("IMEA workbook com abas repetidas")
    missing = sorted(EXPECTED_SHEETS - set(sheets))
    if missing:
        raise ValueError(f"IMEA workbook sem abas obrigatorias: {missing}")

    records: list[ImeaRecord] = []
    natural_keys: Counter[tuple[Any, ...]] = Counter()
    qa = {"progress_null_cells": 0, "progress_out_of_range": 0}

    for sheet_name in ("indicadores diarios", "indicadores semanais"):
        idx, rows = _header(sheets[sheet_name])
        required = {"DATA", "PRODUTO", "INFORMAÇÃO", "LOCAL", "UNIDADE", "DADO"}
        if not required <= set(idx):
            raise ValueError(f"{sheet_name}: colunas ausentes {sorted(required-set(idx))}")
        for row in rows:
            value = _get(row, idx, "DADO")
            if value in (None, ""):
                continue
            date = excel_date(_get(row, idx, "DATA"))
            product = str(_get(row, idx, "PRODUTO")).strip()
            metric = str(_get(row, idx, "INFORMAÇÃO")).strip()
            local = str(_get(row, idx, "LOCAL")).strip()
            unit_origin = str(_get(row, idx, "UNIDADE")).strip()
            key = (sheet_name, date, product, metric, local, unit_origin)
            natural_keys[key] += 1
            records.append(ImeaRecord(
                record_id=_hash_record(list(key)), source_id=SOURCE_ID, source_sheet=sheet_name,
                data_referencia=date, produto=product, metric_name=metric, valor=float(value),
                unidade_origem=unit_origin, unidade_canonica=normalize_unit(unit_origin), local=local,
            ))

    idx, rows = _header(sheets["frete"])
    required = {"DATA", "PRODUTO", "TIPO_FRETE", "ORIGEM", "DESTINO", "FRETE", "UNIDADE"}
    if not required <= set(idx):
        raise ValueError(f"frete: colunas ausentes {sorted(required-set(idx))}")
    for row in rows:
        value = _get(row, idx, "FRETE")
        if value in (None, ""):
            continue
        date = excel_date(_get(row, idx, "DATA"))
        product = str(_get(row, idx, "PRODUTO")).strip()
        metric = str(_get(row, idx, "TIPO_FRETE")).strip()
        origin = str(_get(row, idx, "ORIGEM")).strip()
        destination = str(_get(row, idx, "DESTINO")).strip()
        unit_origin = str(_get(row, idx, "UNIDADE")).strip()
        key = ("frete", date, product, metric, origin, destination, unit_origin)
        natural_keys[key] += 1
        records.append(ImeaRecord(
            record_id=_hash_record(list(key)), source_id=SOURCE_ID, source_sheet="frete",
            data_referencia=date, produto=product, metric_name=metric, valor=float(value),
            unidade_origem=unit_origin, unidade_canonica=normalize_unit(unit_origin),
            origem=origin, destino=destination, evidence_class="observado",
            evidence_subtype="imea_freight_reference", negotiated=False,
        ))

    for sheet_name, metric_name in (("semeadura", "PROGRESSO SEMEADURA"), ("colheita", "PROGRESSO COLHEITA")):
        idx, rows = _header(sheets[sheet_name])
        required = {"DATA", "PRODUTO", "SAFRA", *REGIONS}
        if not required <= set(idx):
            raise ValueError(f"{sheet_name}: colunas ausentes {sorted(required-set(idx))}")
        for row in rows:
            date = excel_date(_get(row, idx, "DATA"))
            product = str(_get(row, idx, "PRODUTO")).strip()
            season = str(_get(row, idx, "SAFRA")).strip()
            for region in REGIONS:
                value = _get(row, idx, region)
                if value in (None, ""):
                    qa["progress_null_cells"] += 1
                    continue
                numeric = float(value)
                if numeric < 0 or numeric > 1.000001:
                    qa["progress_out_of_range"] += 1
                key = (sheet_name, date, product, season, region)
                natural_keys[key] += 1
                records.append(ImeaRecord(
                    record_id=_hash_record(list(key)), source_id=SOURCE_ID, source_sheet=sheet_name,
                    data_referencia=date, produto=product, metric_name=metric_name, valor=numeric,
                    unidade_origem="proporcao", unidade_canonica="proporcao", safra=season, regiao=region,
                    evidence_class="estimado", evidence_subtype="imea_crop_progress_estimate",
                ))

    duplicates = sum(count - 1 for count in natural_keys.values() if count > 1)
    if duplicates:
        raise ValueError(f"IMEA workbook possui {duplicates} duplicidades de chave natural")
    if qa["progress_out_of_range"]:
        raise ValueError(f"IMEA progresso fora de [0,1]: {qa['progress_out_of_range']}")

    sheet_counts = Counter(record.source_sheet for record in records)
    if not records:
        raise ValueError("IMEA workbook sem observações válidas")
    dates = [record.data_referencia for record in records]
    return {
        "source_id": SOURCE_ID,
        "records": [record.to_dict() for record in records],
        "qa": {
            **qa,
            "records": len(records),
            "sheet_counts": dict(sheet_counts),
            "first_date": min(dates) if dates else None,
            "last_date": max(dates) if dates else None,
            "natural_key_duplicates": duplicates,
        },
    }
