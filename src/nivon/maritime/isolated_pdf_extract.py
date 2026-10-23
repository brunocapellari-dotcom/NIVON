"""Parent-side subprocess contract for bounded PDF table extraction.

No network access is requested. POSIX CPU/RAM limits apply inside worker.
The caller still requires independent licensing, untrusted-input OS sandboxing,
and published-source homologation before production.
"""
from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys

from nivon._agrolog_portos_pdf import (
    PdfTable, MAX_PDF_TABLES, MAX_PDF_ROWS, MAX_PDF_CELLS, MAX_PDF_PAGES,
)
from .pdf_extraction_worker import MAX_INPUT, MAX_JSON


MAX_CELL_CHARS = 4096
MAX_ROWS_PER_TABLE = MAX_PDF_ROWS


def extract_pdf_tables_isolated(
    source: bytes, *, timeout_seconds: int = 25,
) -> tuple[PdfTable, ...]:
    """Reject failed child, forged hash, oversized or malformed structured output."""
    if os.name != "posix":
        raise RuntimeError("offline PDF isolation requires POSIX resource limits")
    if not isinstance(source, bytes) or not 0 < len(source) <= MAX_INPUT:
        raise ValueError("isolated PDF byte quota exceeded")
    if not 1 <= timeout_seconds <= 60:
        raise ValueError("invalid PDF extraction timeout")
    if not source.startswith(b"%PDF-"):
        raise ValueError("invalid PDF signature")
    digest = hashlib.sha256(source).hexdigest()
    try:
        process = subprocess.run(
            [sys.executable, "-m", "nivon.maritime.pdf_extraction_worker"],
            input=source, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            timeout=timeout_seconds, check=False, close_fds=True,
        )
    except subprocess.TimeoutExpired as exc:
        raise ValueError("isolated PDF extraction timed out") from exc
    if process.returncode != 0:
        raise ValueError("isolated PDF extraction failed or resource limit reached")
    if not 0 < len(process.stdout) <= MAX_JSON:
        raise ValueError("isolated PDF output size invalid")
    try:
        payload = json.loads(process.stdout)
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise ValueError("isolated PDF worker returned invalid JSON") from exc
    if (not isinstance(payload, dict)
            or type(payload.get("schema_version")) is not int
            or payload["schema_version"] != 1
            or payload.get("source_sha256") != digest):
        raise ValueError("isolated PDF worker did not attest matching original bytes")
    raw_tables = payload.get("tables")
    if not isinstance(raw_tables, list) or not 0 < len(raw_tables) <= MAX_PDF_TABLES:
        raise ValueError("isolated PDF worker table quota exceeded")
    total_rows = 0
    total_cells = 0
    result: list[PdfTable] = []
    for table in raw_tables:
        if not isinstance(table, dict):
            raise ValueError("isolated PDF table schema invalid")
        page = table.get("page_number")
        rows = table.get("rows")
        if (type(page) is not int or not 1 <= page <= MAX_PDF_PAGES
                or not isinstance(rows, list) or not 0 < len(rows) <= MAX_ROWS_PER_TABLE):
            raise ValueError("isolated PDF page/row schema invalid")
        normalized: list[tuple[str, ...]] = []
        for row in rows:
            if not isinstance(row, list) or not row or len(row) > 100:
                raise ValueError("isolated PDF cell count invalid")
            if any(not isinstance(cell, str) or len(cell) > MAX_CELL_CHARS for cell in row):
                raise ValueError("isolated PDF text cell invalid")
            total_cells += len(row)
            normalized.append(tuple(row))
        total_rows += len(rows)
        if total_rows > MAX_PDF_ROWS or total_cells > MAX_PDF_CELLS:
            raise ValueError("isolated PDF total quota exceeded")
        result.append(PdfTable(page_number=page, rows=tuple(normalized)))
    return tuple(result)
