"""Child process for bounded PDF table extraction. Offline only.

This is resource-isolated parsing, NOT a full security sandbox: the child
runs with the same OS user and is not denied network at OS level. Processing
untrusted external PDFs in production also requires containers/seccomp,
read-only filesystem, no network, per-source rights and manual homologation.
"""
from __future__ import annotations

import hashlib
import json
import os
import sys

from nivon._agrolog_portos_pdf import extract_pdf_tables

MAX_INPUT = 20_000_000
MAX_JSON = 6_000_000


def _limits() -> None:
    """Mandatory POSIX CPU and address-space limits, applied before pdfplumber."""
    if os.name != "posix":
        raise RuntimeError("isolated PDF worker requires POSIX process limits")
    import resource

    # Use smaller than typical CI runner memory, large enough for pdfminer.
    resource.setrlimit(resource.RLIMIT_CPU, (12, 14))
    resource.setrlimit(resource.RLIMIT_AS, (1024 * 1024 * 1024,) * 2)
    resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
    try:
        os.nice(10)
    except OSError:
        pass


def main() -> int:
    try:
        _limits()
        source = sys.stdin.buffer.read(MAX_INPUT + 1)
        if not 0 < len(source) <= MAX_INPUT or not source.startswith(b"%PDF-"):
            raise ValueError("invalid PDF worker input")
        tables = extract_pdf_tables(source)
        record = {
            "schema_version": 1,
            "source_sha256": hashlib.sha256(source).hexdigest(),
            "tables": [
                {"page_number": table.page_number,
                 "rows": [list(row) for row in table.rows]}
                for table in tables
            ],
        }
        blob = json.dumps(
            record, ensure_ascii=False, separators=(",", ":"), allow_nan=False
        ).encode("utf-8")
        if len(blob) > MAX_JSON:
            raise ValueError("isolated PDF output exceeds quota")
        sys.stdout.buffer.write(blob)
        return 0
    except (ValueError, RuntimeError, OSError, MemoryError) as exc:
        # Don't emit portions of the raw file or a trace of its content.
        sys.stderr.write("PDF_WORKER_BLOCKED: " + type(exc).__name__ + "\n")
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
