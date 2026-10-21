# Reuso interno NIVON: origem brunocapellari-dotcom/AgroLogMT/collector/official_lineup_html.py (branch main, 2026-10-19).
# Direitos/proveniência: código de repositório da mesma conta; verificar antes de distribuir externamente.
# Sem habilitar rede, AIS ou credenciais por importação.
from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from html.parser import HTMLParser
from typing import Iterable
from urllib.error import HTTPError
from urllib.parse import urlparse
from urllib.request import HTTPRedirectHandler, Request, build_opener


ALLOWED_HOSTS = frozenset({"www.portodesantos.com.br", "www.cdp.com.br"})


@dataclass(frozen=True)
class HtmlTable:
    context: str
    rows: tuple[tuple[str, ...], ...]


@dataclass(frozen=True)
class FetchedHtml:
    url: str
    status_code: int
    content_type: str | None
    body: bytes
    text: str
    etag: str | None = None
    last_modified: str | None = None


class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):  # noqa: ANN001
        return None


class _TableParser(HTMLParser):
    """Small deterministic HTML-table extractor with nearby section context.

    It deliberately does not execute JavaScript. If an official page stops exposing
    its table in HTML, the source fails closed and must move to a different adapter.
    """

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.tables: list[HtmlTable] = []
        self._in_table = False
        self._in_row = False
        self._in_cell = False
        self._cell_parts: list[str] = []
        self._row: list[str] = []
        self._rows: list[tuple[str, ...]] = []
        self._outside_parts: list[str] = []
        self._table_context = ""

    @staticmethod
    def _clean(parts: Iterable[str]) -> str:
        return " ".join(" ".join(parts).replace("\xa0", " ").split())

    def handle_starttag(self, tag: str, attrs) -> None:  # noqa: ANN001
        tag = tag.lower()
        if tag == "table" and not self._in_table:
            self._in_table = True
            self._rows = []
            self._table_context = self._clean(self._outside_parts[-80:])[-2500:]
        elif self._in_table and tag == "tr":
            self._in_row = True
            self._row = []
        elif self._in_row and tag in {"th", "td"}:
            self._in_cell = True
            self._cell_parts = []

    def handle_endtag(self, tag: str) -> None:
        tag = tag.lower()
        if self._in_cell and tag in {"th", "td"}:
            self._row.append(self._clean(self._cell_parts))
            self._cell_parts = []
            self._in_cell = False
        elif self._in_row and tag == "tr":
            if self._row and any(cell for cell in self._row):
                self._rows.append(tuple(self._row))
            self._row = []
            self._in_row = False
        elif self._in_table and tag == "table":
            if self._rows:
                self.tables.append(HtmlTable(self._table_context, tuple(self._rows)))
            self._rows = []
            self._in_table = False

    def handle_data(self, data: str) -> None:
        if not data or not data.strip():
            return
        if self._in_cell:
            self._cell_parts.append(data)
        elif not self._in_table:
            self._outside_parts.append(data)
            if len(self._outside_parts) > 500:
                del self._outside_parts[:250]


def _ascii_key(value: str) -> str:
    text = unicodedata.normalize("NFKD", value).encode("ascii", "ignore").decode("ascii")
    return re.sub(r"[^a-z0-9]+", "_", text.lower()).strip("_")


def _canonical_header(value: str) -> str:
    key = _ascii_key(value)
    # Multilingual Santos headers become strings such as data_date_fecha.
    for prefix, canonical in (
        ("data", "data"),
        ("hora", "hora"),
        ("eta", "eta"),
        ("local", "local"),
        ("navio", "navio"),
        ("imo", "imo"),
        ("carga", "carga"),
        ("evento", "evento"),
        ("viagem", "viagem"),
        ("duv", "duv"),
        ("wdt_id", "wdt_id"),
        ("quantidade", "quantidade_t"),
        ("chegada", "chegada"),
        ("atracacao", "atracacao"),
        ("desatracacao", "desatracacao"),
        ("cliente", "cliente"),
        ("operador", "operador"),
        ("agente", "agente"),
    ):
        if key == prefix or key.startswith(prefix + "_"):
            return canonical
    return key


def extract_tables(html: str) -> list[HtmlTable]:
    parser = _TableParser()
    parser.feed(html)
    parser.close()
    return parser.tables


def _table_records(table: HtmlTable, required: set[str]) -> list[dict[str, str]]:
    header_index = None
    headers: list[str] = []
    for idx, row in enumerate(table.rows):
        candidate = [_canonical_header(cell) for cell in row]
        if required.issubset(set(candidate)):
            header_index = idx
            headers = candidate
            break
    if header_index is None:
        return []

    records: list[dict[str, str]] = []
    for row in table.rows[header_index + 1 :]:
        if not any(cell.strip() for cell in row):
            continue
        values = list(row) + [""] * max(0, len(headers) - len(row))
        record = {headers[i]: values[i].strip() for i in range(min(len(headers), len(values))) if headers[i]}
        if record:
            records.append(record)
    return records


def _cdp_terminal(context: str) -> str | None:
    normalized = unicodedata.normalize("NFKD", context).encode("ascii", "ignore").decode("ascii").upper()
    candidates: list[tuple[int, str]] = []
    for match in re.finditer(r"\bBERCO\s+(\d{2,4})\b", normalized):
        candidates.append((match.start(), f"BERCO_{match.group(1)}"))
    for match in re.finditer(r"\b(?:NO FUNDEIO|AT ANCHORAGE)\b", normalized):
        candidates.append((match.start(), "FUNDEIO"))
    for match in re.finditer(r"\bRAMPA RODOFLUVIAL\b", normalized):
        candidates.append((match.start(), "RAMPA_RODOFLUVIAL"))
    return max(candidates, key=lambda item: item[0])[1] if candidates else None


def parse_santos_schedule(html: str) -> list[dict[str, str]]:
    """Parse APS Atracações Programadas without promoting a schedule to realized.

    `Evento=ATRACACAO/REATRACACAO/MUDANCA` describes the programmed maneuver.
    It is preserved as `source_event`; analytical status remains PROGRAMMED.
    """
    output: list[dict[str, str]] = []
    for table in extract_tables(html):
        for record in _table_records(table, {"navio", "imo", "eta", "duv"}):
            vessel = record.get("navio", "").strip()
            eta = record.get("eta", "").strip()
            if not vessel or not eta:
                continue
            output.append({
                "navio": vessel,
                "imo": record.get("imo", "").strip(),
                "eta": eta,
                "terminal": record.get("local", "").strip(),
                "carga": record.get("carga", "").strip(),
                "status": "PROGRAMMED",
                "duv": record.get("duv", "").strip(),
                "viagem": record.get("viagem", "").strip(),
                "source_event": record.get("evento", "").strip(),
                "scheduled_date": record.get("data", "").strip(),
                "scheduled_window": record.get("hora", "").strip(),
            })
    return output


def parse_cdp_programming(html: str) -> list[dict[str, str]]:
    """Parse CDP programming tables while preserving their scheduled semantics.

    CHEGADA is used as ETA. ATRACAÇÃO/DESATRACAÇÃO remain source schedule fields;
    they are never transformed into observed berth/departure events by this parser.
    """
    output: list[dict[str, str]] = []
    for table in extract_tables(html):
        terminal = _cdp_terminal(table.context)
        records = _table_records(table, {"navio", "carga", "quantidade_t", "chegada"})
        for record in records:
            vessel = record.get("navio", "").strip()
            eta = record.get("chegada", "").strip()
            if not vessel or _ascii_key(vessel) in {"navio", "vessel"} or not eta:
                continue
            row = {
                "navio": vessel,
                "eta": eta,
                "terminal": terminal or "",
                "carga": record.get("carga", "").strip(),
                "quantidade_t": record.get("quantidade_t", "").strip(),
                "status": "PROGRAMMED",
                "scheduled_berth": record.get("atracacao", "").strip(),
                "scheduled_unberth": record.get("desatracacao", "").strip(),
                "cliente": record.get("cliente", "").strip(),
                "operador": record.get("operador", "").strip(),
                "agente": record.get("agente", "").strip(),
            }
            source_row_id = record.get("wdt_id", "").strip()
            if source_row_id:
                # Scope the WordPress/DataTables row id by terminal to avoid collisions.
                row["call_id"] = f"{terminal or 'SEM_TERMINAL'}:{source_row_id}"
            output.append(row)
    return output


def parse_official_lineup_html(html: str, parser_mode: str) -> list[dict[str, str]]:
    if parser_mode == "HTML_SANTOS_SCHEDULE":
        return parse_santos_schedule(html)
    if parser_mode == "HTML_CDP_BERTH_TABLE":
        return parse_cdp_programming(html)
    raise ValueError(f"parser HTML não suportado: {parser_mode}")


