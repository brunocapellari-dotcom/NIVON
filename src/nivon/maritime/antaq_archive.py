"""ANTAQ annual Estatistico Aquaviario offline ZIP: rigorous monthly aggregates.

No network, hidden retries, raw vessel inference, publication or implicit rights.
A single call may have multiple cargo rows: never count cargo rows as port calls.
Published period (Ano/Mes) is distinct from reported berth timestamp.
"""
from __future__ import annotations

import csv
import hashlib
import io
import math
import re
import zipfile
from collections import defaultdict
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from typing import Any

MAX_ZIP_BYTES = 150_000_000
MAX_UNCOMPRESSED = 1_200_000_000
MAX_ROWS = 6_000_000
_MONTHS = dict(zip(
    ("jan","fev","mar","abr","mai","jun","jul","ago","set","out","nov","dez"),
    range(1, 13),
))
_REQUIRED = {
    "Atracacao": {"IDAtracacao", "Porto Atracação", "Terminal", "SGUF", "Ano", "Mes"},
    "Carga": {"IDAtracacao", "CDMercadoria", "VLPesoCargaBruta", "Sentido", "Natureza da Carga", "Tipo Navegação"},
    "Mercadoria": {"CDMercadoria", "Nomenclatura Simplificada Mercadoria"},
}


def _utc(value: str | datetime, label: str) -> str:
    try:
        dt = value if isinstance(value, datetime) else datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{label}: data invalida") from exc
    if dt.tzinfo is None or dt.utcoffset() is None:
        raise ValueError(f"{label}: timezone requerido")
    return dt.astimezone(timezone.utc).isoformat()


def _mes(raw: str) -> int:
    raw = raw.strip().lower().rstrip(".")
    if raw.isdigit() and 1 <= int(raw) <= 12:
        return int(raw)
    month = _MONTHS.get(raw[:3])
    if month is None:
        raise ValueError("mes publicado desconhecido")
    return month


def _weight(value: str) -> Decimal:
    s = value.strip().replace("\u00a0", "").replace(" ", "")
    if not s or not re.fullmatch(r"-?(?:\d+|\d{1,3}(?:\.\d{3})+)(?:,\d+)?", s):
        raise ValueError("peso ANTAQ invalido")
    try:
        dec = Decimal(s.replace(".", "").replace(",", "."))
    except InvalidOperation as exc:
        raise ValueError("peso invalido") from exc
    if dec < 0 or not dec.is_finite():
        raise ValueError("peso negativo ou infinito")
    return dec


def _normalized_filename(name: str, year: int) -> str | None:
    basename = name.rsplit("/", 1)[-1]
    name = basename.strip()
    for kind in _REQUIRED:
        if re.fullmatch(rf"(?:{year})?{kind}\.txt", name, flags=re.I):
            return kind
    return None


@dataclass(frozen=True)
class AntaqArchiveSummary:
    source_id: str
    archive_sha256: str
    archive_year: int
    collected_at: str
    classification: str
    status: str
    count_atracacoes_distinct: int
    count_carga_rows: int
    count_carga_without_atracacao: int
    count_aggregated_groups: int
    publication_allowed: bool
    warnings: tuple[str, ...]
    monthly_port_cargo: tuple[dict[str, Any], ...]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def analyze_antaq_archive(
    payload: bytes, *, year: int, source_id: str, collected_at: str | datetime,
    rights_to_read: bool = False, max_cargo_rows: int = MAX_ROWS,
) -> AntaqArchiveSummary:
    """Build monthly throughput from a verified, locally provided annual ZIP.

    Fail closed if key, headers or catalog conflicts are ambiguous. The output
    is statistical historical cargo data, never independently confirmed ship cargo.
    """
    if not rights_to_read:
        raise PermissionError("ANTAQ: autorizacao de uso do arquivo nao verificada")
    if not source_id or not source_id.strip():
        raise ValueError("source_id obrigatorio")
    if not isinstance(year, int) or not 2010 <= year <= 2100:
        raise ValueError("ano de arquivo invalido")
    collected = _utc(collected_at, "collected_at")
    if not isinstance(payload, bytes) or not payload or len(payload) > MAX_ZIP_BYTES:
        raise ValueError("ZIP vazio ou excessivo")
    if not 1 <= max_cargo_rows <= MAX_ROWS:
        raise ValueError("max_cargo_rows fora de faixa")
    digest = hashlib.sha256(payload).hexdigest()
    with zipfile.ZipFile(io.BytesIO(payload), "r") as archive:
        selected = {}
        total_size = 0
        for info in archive.infolist():
            # No archive extraction; still forbid suspicious names and dangerous sizes.
            parts = info.filename.replace("\\", "/").split("/")
            if info.is_dir():
                continue
            if (not info.filename or any(part in {"", ".", ".."} for part in parts)
                    or info.filename.startswith("/") or ":" in info.filename
                    or info.file_size > MAX_UNCOMPRESSED):
                raise ValueError("ZIP contem entrada insegura")
            total_size += info.file_size
            if total_size > MAX_UNCOMPRESSED:
                raise ValueError("ZIP descomprimido excessivo")
            if info.file_size > 1_000_000 and info.file_size > 1000 * max(1, info.compress_size):
                raise ValueError("ZIP altamente comprimido suspeito")
            kind = _normalized_filename(info.filename, year)
            if kind is not None:
                if kind in selected:
                    raise ValueError(f"{kind}: arquivo duplicado")
                selected[kind] = info
        if set(selected) != set(_REQUIRED):
            raise ValueError(f"arquivos obrigatorios ausentes: {sorted(set(_REQUIRED)-set(selected))}")

        def rows(kind):
            with archive.open(selected[kind]) as stream:
                with io.TextIOWrapper(stream, encoding="utf-8-sig", errors="strict", newline="") as text:
                    reader = csv.DictReader(text, delimiter=";", strict=True)
                    if reader.fieldnames is None:
                        raise ValueError(f"{kind}: cabecalho ausente")
                    header = [x.strip() for x in reader.fieldnames]
                    if len(header) != len(set(header)) or not _REQUIRED[kind].issubset(header):
                        raise ValueError(f"{kind}: esquema incompleto ou duplicado: {header}")
                    for row in reader:
                        if None in row or any(v is None for v in row.values()):
                            raise ValueError(f"{kind}: linha com cardinalidade de colunas incorreta")
                        yield {str(k).strip(): v.strip() for k, v in row.items()}

        # Load attribution ID map only, not the giant Cargo table.
        atracacoes = {}
        for i, row in enumerate(rows("Atracacao"), start=1):
            if i > MAX_ROWS:
                raise ValueError("Atracacao excede limite")
            key = row["IDAtracacao"]
            if not key or key in atracacoes:
                raise ValueError("IDAtracacao ausente ou repetida")
            ref_year = row["Ano"]
            if not re.fullmatch(r"\d{4}", ref_year) or int(ref_year) != year:
                raise ValueError("Ano da atracacao incompativel com arquivo anual")
            port = row["Porto Atracação"]
            uf = row["SGUF"].upper()
            if not port or not re.fullmatch("[A-Z]{2}", uf):
                raise ValueError("porto/UF invalidos")
            month = _mes(row["Mes"])
            atracacoes[key] = (year, month, port, row["Terminal"], uf)
        if not atracacoes:
            raise ValueError("arquivo sem atracacoes")

        commodity = {}
        for i, row in enumerate(rows("Mercadoria"), start=1):
            if i > 200_000:
                raise ValueError("catalogo mercadoria excessivo")
            key = row["CDMercadoria"]
            name = row["Nomenclatura Simplificada Mercadoria"]
            if not key:
                raise ValueError("codigo mercadoria ausente")
            if key in commodity and commodity[key] != name:
                raise ValueError("mercadoria com mapeamento contraditorio")
            commodity[key] = name

        aggregates: dict[tuple, list[Any]] = defaultdict(lambda: [Decimal(0), 0])
        matched = 0
        orphan = 0
        for i, row in enumerate(rows("Carga"), start=1):
            if i > max_cargo_rows:
                raise ValueError("Carga excede limite configurado")
            link = atracacoes.get(row["IDAtracacao"])
            if link is None:
                orphan += 1
                continue
            kg = _weight(row["VLPesoCargaBruta"])
            # VLPesoCargaBruta is published in tonnes in the EA datasets.
            product = commodity.get(row["CDMercadoria"])
            if product is None:
                product = ""
            group = (*link, row["CDMercadoria"], product,
                     row["Sentido"], row["Natureza da Carga"],
                     row["Tipo Navegação"])
            aggregates[group][0] += kg
            aggregates[group][1] += 1
            matched += 1
        total = matched + orphan
        if not total:
            raise ValueError("arquivo Carga vazio")
        output = []
        for key, (tonnes, rows_count) in sorted(aggregates.items()):
            yr, month, port, terminal, uf, product_code, product, direction, nature, navigation = key
            output.append({
                "year": yr, "month": month, "port_name_published": port,
                "terminal_name_published": terminal, "uf": uf,
                "commodity_code": product_code, "commodity_name_published": product or None,
                "direction_published": direction, "cargo_nature_published": nature,
                "navigation_published": navigation,
                "gross_tonnes_published": str(tonnes),
                "source_cargo_rows": rows_count,
                "source_id": source_id, "source_sha256": digest,
                "competence": f"{yr:04d}-{month:02d}",
                "evidence_class": "DECLARADO_ESTATISTICO_ANTAQ",
                "observed_ship_count": None,  # Cargo rows != number of port calls.
            })
        warnings = []
        if orphan:
            warnings.append("cargo_orphan_rows: reconciliar IDAtracacao sem converter zero")
        if any(not x["commodity_name_published"] for x in output):
            warnings.append("unknown_commodity_code_in_source")
        return AntaqArchiveSummary(
            source_id=source_id, archive_sha256=digest, archive_year=year,
            collected_at=collected,
            classification="HISTORICO_MENSAL_DECLARADO_NAO_AIS",
            status="OFFLINE_SOURCE_FILE_ONLY",
            count_atracacoes_distinct=len(atracacoes),
            count_carga_rows=total,
            count_carga_without_atracacao=orphan,
            count_aggregated_groups=len(output),
            publication_allowed=False,
            warnings=tuple(warnings),
            monthly_port_cargo=tuple(output),
        )
