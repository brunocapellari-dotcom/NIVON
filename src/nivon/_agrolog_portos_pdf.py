# Reuso interno NIVON: origem brunocapellari-dotcom/AgroLogMT/collector/official_lineup_pdf.py (branch main, 2026-10-19).
# Direitos/proveniência: código de repositório da mesma conta; verificar antes de distribuir externamente.
# Sem habilitar rede, AIS ou credenciais por importação.
from __future__ import annotations

import io
import re
import unicodedata
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from html.parser import HTMLParser
from typing import Any, Iterable
from urllib.parse import urljoin, urlparse


PDF_ALLOWED_HOSTS = frozenset({
    "www.portosdoparana.pr.gov.br",
    "portosdoparana.pr.gov.br",
    "www.portodoitaqui.com",
    "portodoitaqui.com",
})


@dataclass(frozen=True)
class PdfTable:
    page_number: int
    rows: tuple[tuple[str, ...], ...]


class _LinkParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.links: list[tuple[str, str]] = []
        self._href: str | None = None
        self._parts: list[str] = []

    def handle_starttag(self, tag: str, attrs) -> None:  # noqa: ANN001
        if tag.lower() != "a":
            return
        href = dict(attrs).get("href")
        if href:
            self._href = str(href)
            self._parts = []

    def handle_data(self, data: str) -> None:
        if self._href and data.strip():
            self._parts.append(data)

    def handle_endtag(self, tag: str) -> None:
        if tag.lower() == "a" and self._href:
            self.links.append((" ".join(" ".join(self._parts).split()), self._href))
            self._href = None
            self._parts = []


def _ascii(value: Any) -> str:
    text = unicodedata.normalize("NFKD", str(value or "")).encode("ascii", "ignore").decode("ascii")
    return " ".join(text.replace("\xa0", " ").split())


def _key(value: Any) -> str:
    return re.sub(r"[^a-z0-9]+", "_", _ascii(value).lower()).strip("_")


def _cell(value: Any) -> str:
    if value is None:
        return ""
    return " ".join(str(value).replace("\xa0", " ").split())


def _validate_pdf_url(url: str) -> None:
    parsed = urlparse(url)
    if parsed.scheme != "https":
        raise ValueError("fonte PDF maritime exige HTTPS")
    if parsed.hostname not in PDF_ALLOWED_HOSTS:
        raise ValueError(f"host PDF maritime não autorizado: {parsed.hostname}")
    if parsed.username or parsed.password:
        raise ValueError("URL PDF com credencial embutida é proibida")


def extract_links(html: str, base_url: str) -> list[tuple[str, str]]:
    parser = _LinkParser()
    parser.feed(html)
    parser.close()
    output: list[tuple[str, str]] = []
    for text, href in parser.links:
        absolute = urljoin(base_url, href)
        parsed = urlparse(absolute)
        if parsed.scheme == "https" and parsed.hostname in PDF_ALLOWED_HOSTS and not parsed.username and not parsed.password:
            output.append((text, absolute))
    return output


def discover_pdf_link_from_landing(html: str, landing_url: str) -> str:
    candidates = [url for _, url in extract_links(html, landing_url) if urlparse(url).path.lower().endswith(".pdf")]
    unique = list(dict.fromkeys(candidates))
    if not unique:
        raise ValueError("landing page oficial sem link PDF")
    if len(unique) != 1:
        raise ValueError(f"landing page oficial com {len(unique)} PDFs; seleção ambígua")
    _validate_pdf_url(unique[0])
    return unique[0]


def _label_date(text: str) -> date | None:
    match = re.search(r"\b(\d{2})/(\d{2})/(\d{4})\b", text)
    if not match:
        return None
    try:
        return date(int(match.group(3)), int(match.group(2)), int(match.group(1)))
    except ValueError:
        return None


def discover_paranagua_landing_pages(html: str, index_url: str) -> dict[str, str]:
    patterns = {
        "EXPORT_OESTE": re.compile(r"\bLINE[- ]?UP\s+CORREDOR\s+OESTE\b", re.I),
        "EXPORT_LESTE": re.compile(r"\bLINE[- ]?UP\s+CORREDOR\s+LESTE\b", re.I),
        "IMPORT_SOLIDOS": re.compile(r"\bLINE\s*UP\s+DE\s+GRANEIS\s+SOLIDOS\s+DE\s+IMPORTACAO\b", re.I),
    }
    best: dict[str, tuple[date, str]] = {}
    for text, url in extract_links(html, index_url):
        normalized = _ascii(text)
        if "ATA DE ATRAC" in normalized.upper():
            continue
        observed_date = _label_date(normalized)
        if observed_date is None:
            continue
        for series, pattern in patterns.items():
            if pattern.search(normalized):
                previous = best.get(series)
                if previous is None or observed_date > previous[0]:
                    best[series] = (observed_date, url)
    return {series: item[1] for series, item in best.items()}


def extract_pdf_tables(payload: bytes) -> list[PdfTable]:
    if not payload.startswith(b"%PDF"):
        raise ValueError("payload não é PDF")
    try:
        import pdfplumber
    except ImportError as exc:  # pragma: no cover
        raise RuntimeError("pdfplumber não instalado; requirements-collector incompleto") from exc

    tables: list[PdfTable] = []
    with pdfplumber.open(io.BytesIO(payload)) as pdf:
        for page_number, page in enumerate(pdf.pages, start=1):
            for table in page.extract_tables() or []:
                rows = tuple(tuple(_cell(cell) for cell in row) for row in table if row)
                if rows:
                    tables.append(PdfTable(page_number=page_number, rows=rows))
    if not tables:
        raise ValueError("PDF oficial sem tabelas extraíveis")
    return tables


def _find_header(rows: Iterable[tuple[str, ...]], required_groups: tuple[tuple[str, ...], ...]) -> tuple[int, list[str]] | None:
    for idx, row in enumerate(rows):
        keys = [_key(cell) for cell in row]
        joined = " ".join(keys)
        if all(any(token in joined for token in group) for group in required_groups):
            return idx, keys
    return None


def _index_for(headers: list[str], *tokens: str, before: int | None = None, after: int | None = None) -> int | None:
    for idx, header in enumerate(headers):
        if before is not None and idx >= before:
            continue
        if after is not None and idx <= after:
            continue
        if any(token in header for token in tokens):
            return idx
    return None


def _index_exact_or_contains(headers: list[str], preferred: tuple[str, ...], fallback: tuple[str, ...] = ()) -> int | None:
    """Prefer semantically specific headers before broad substring fallbacks."""
    for idx, header in enumerate(headers):
        if any(token in header for token in preferred):
            return idx
    for idx, header in enumerate(headers):
        if any(token in header for token in fallback):
            return idx
    return None


def _value(row: tuple[str, ...], index: int | None) -> str:
    if index is None or index >= len(row):
        return ""
    return _cell(row[index])


def _br_number(value: str) -> float | None:
    text = _cell(value).replace(" ", "")
    if not text or text in {"-", "--"}:
        return None
    text = re.sub(r"[^0-9,.-]", "", text)
    if not text:
        return None
    if "," in text and "." in text:
        text = text.replace(".", "").replace(",", ".")
    elif "," in text:
        text = text.replace(",", ".")
    elif re.fullmatch(r"\d{1,3}(?:\.\d{3})+", text):
        text = text.replace(".", "")
    try:
        return float(text)
    except ValueError:
        return None


def _format_number(value: float | None) -> str:
    if value is None:
        return ""
    return f"{value:.6f}".rstrip("0").rstrip(".")


def _normalize_partial_eta(value: str, reference_date: date) -> str:
    text = _cell(value)
    # A PDF that only prints a calendar date has NOT provided an ETA clock.
    # datetime.strptime would otherwise invent 00:00 and a false precise ETA.
    if not re.search(r"\b\d{1,2}:\d{2}\b", text):
        raise ValueError("eta_clock_missing")
    formats = (
        "%d/%m/%Y %H:%M",
        "%d/%m/%y %H:%M",
        "%d/%m %H:%M",
    )
    for fmt in formats:
        try:
            candidate = datetime.strptime(text, fmt)
        except ValueError:
            continue
        if "%Y" not in fmt and "%y" not in fmt:
            candidate = candidate.replace(year=reference_date.year)
            if candidate.date() - reference_date > timedelta(days=180):
                candidate = candidate.replace(year=reference_date.year - 1)
            elif reference_date - candidate.date() > timedelta(days=180):
                candidate = candidate.replace(year=reference_date.year + 1)
        return candidate.strftime("%d/%m/%Y %H:%M")
    raise ValueError(f"ETA PDF não reconhecido: {value!r}")


def parse_itaqui_tables(tables: Iterable[PdfTable], *, reference_date: date) -> list[dict[str, str]]:
    output: list[dict[str, str]] = []
    for table in tables:
        found = _find_header(
            table.rows,
            (("status",), ("imo",), ("navio", "vessel"), ("produto", "cargo"), ("qtde", "quantidade")),
        )
        if found is None:
            continue
        header_idx, headers = found
        status_i = _index_for(headers, "status")
        imo_i = _index_for(headers, "imo")
        vessel_i = _index_for(headers, "navio", "vessel")
        product_i = _index_for(headers, "produto", "cargo")
        qty_i = _index_for(headers, "qtde", "quantidade")
        eta_i = _index_exact_or_contains(
            headers,
            ("prev_chegada", "eta_nor", "chegada_eta", "estimated_arrival"),
            ("chegada",),
        )
        # Do not let generic `chegada` resolve to `calado_de_chegada`.
        if eta_i is not None and "calado" in headers[eta_i]:
            eta_i = next(
                (idx for idx, header in enumerate(headers) if "chegada" in header and "calado" not in header),
                None,
            )
        berth_i = _index_for(headers, "berco", "berth", before=status_i)
        duv_i = _index_exact_or_contains(
            headers, ("duv", "numero_unico_de_viagem"), ()
        )
        if None in (status_i, vessel_i, product_i, qty_i, eta_i):
            continue

        current_berth = ""
        for row in table.rows[header_idx + 1 :]:
            status = _value(row, status_i).upper()
            vessel = _value(row, vessel_i)
            if not vessel or status not in {"ATRACADO", "FUNDEADO", "ESPERADO"}:
                continue
            if _key(vessel) in {"berco_livre", "manutencao"}:
                continue
            berth_match = re.search(r"\bBER[CÇ]O\s*(\d{1,3})\b", _value(row, berth_i), re.I)
            if berth_match:
                current_berth = f"BERCO_{berth_match.group(1)}"
            try:
                eta = _normalize_partial_eta(_value(row, eta_i), reference_date)
            except ValueError:
                # Keep the source row visible for audit; never substitute 00:00
                # or silently shrink the apparent line-up during parsing.
                eta = ""
            imo_raw = _value(row, imo_i)
            imo = re.sub(r"\D", "", imo_raw) if imo_raw else ""
            if imo and len(imo) != 7:
                imo = ""
            output.append({
                "navio": vessel,
                "imo": imo,
                "eta": eta,
                "terminal": current_berth,
                "carga": _value(row, product_i),
                "quantidade_t": _format_number(_br_number(_value(row, qty_i))),
                "status": status,
                "source_status": status,
                # Only an explicit voyage ID column counts as a DUV. Never
                # derive a port-call ID from IMO, vessel name or row number.
                "duv": _value(row, duv_i),
            })
    return output


def _paranagua_volume_and_product(row: tuple[str, ...], headers: list[str], product_i: int | None) -> tuple[str, float | None]:
    named_product = _value(row, product_i).strip() if product_i is not None else ""
    candidates: list[tuple[str, float]] = []
    commodity_tokens = {
        "soja": "SOJA",
        "farelo": "FARELO",
        "milho": "MILHO",
        "acucar": "ACUCAR",
        "outros": "OUTROS",
        "trigo": "TRIGO",
    }
    for idx, header in enumerate(headers):
        for token, label in commodity_tokens.items():
            if token in header:
                value = _br_number(_value(row, idx))
                if value is not None and value > 0:
                    candidates.append((label, value))
                break
    if candidates:
        return named_product or "+".join(label for label, _ in candidates), sum(value for _, value in candidates)
    return named_product, None


def parse_paranagua_tables(
    tables: Iterable[PdfTable],
    *,
    reference_date: date,
    series: str,
) -> list[dict[str, str]]:
    output: list[dict[str, str]] = []
    for table in tables:
        found = _find_header(table.rows, (("navio",), ("n_prog", "prog"), ("chegada",), ("berco",)))
        if found is None:
            continue
        header_idx, headers = found
        preamble = " ".join(_ascii(cell).upper() for row in table.rows[:header_idx] for cell in row)
        if "NAVIOS ATRACADOS" in preamble or "NAVIO ATRACADO" in preamble:
            continue
        if preamble and not any(token in preamble for token in ("LINE UP", "LINE-UP", "PROGRAMADOS")):
            continue

        vessel_i = _index_for(headers, "navio")
        prog_i = _index_for(headers, "n_prog", "prog")
        arrival_i = _index_for(headers, "chegada")
        product_i = _index_for(headers, "produto")
        berth_i = _index_for(headers, "berco")
        duv_i = _index_exact_or_contains(headers, ("duv", "numero_unico_de_viagem"), ())
        if None in (vessel_i, arrival_i, berth_i):
            continue

        for row in table.rows[header_idx + 1 :]:
            vessel = _value(row, vessel_i)
            if not vessel or _key(vessel) in {"navio", "vessel"}:
                continue
            arrival = _value(row, arrival_i)
            if arrival_i + 1 < len(row) and re.fullmatch(r"\d{1,2}:\d{2}", _value(row, arrival_i + 1)):
                arrival = f"{arrival} {_value(row, arrival_i + 1)}".strip()
            if not arrival:
                continue
            try:
                eta = _normalize_partial_eta(arrival, reference_date)
            except ValueError:
                # Preserve the row as unresolvable rather than dropping it.
                # Later official-lineup bridge must exclude and flag it.
                eta = ""
            product, volume = _paranagua_volume_and_product(row, headers, product_i)
            parsed = {
                "navio": vessel,
                "eta": eta,
                "terminal": " ".join(_value(row, berth_i).split()),
                "carga": product,
                "quantidade_t": _format_number(volume),
                "status": "PROGRAMMED",
                "source_series": series,
                "duv": _value(row, duv_i),
            }
            program = _value(row, prog_i)
            if program:
                parsed["call_id"] = f"{series}:{program}"
            output.append(parsed)
    return output
