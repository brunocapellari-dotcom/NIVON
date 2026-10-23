#!/usr/bin/env python3
"""NIVON offline port-PDF batch processor (dry-run by default).

No network acquisition, credentials, live jobs, AIS, or publishing.
Requires a separately recorded human-reviewed rights basis in every entry.
Only explicitly requested --commit --ack-rights writes derived SQLite data.
"""
from __future__ import annotations

import argparse
from datetime import date
import hashlib
import json
from pathlib import Path
import sys
from typing import Any

from nivon.coleta_web import FonteWeb
from nivon.maritime.maritime_store import MaritimeStore
from nivon.maritime.offline_pdf_batch import (
    OfflinePdfEdition, OfflineRightsAttestation, run_offline_pdf_batch,
)
from nivon.maritime.programme_duv_evidence import ProgrammeDuvEvidence
from nivon.portos_automaticos import ContratoPorto

MAX_MANIFEST_BYTES = 250_000


def _manifest(path: Path) -> dict[str, Any]:
    if not path.is_file() or path.stat().st_size > MAX_MANIFEST_BYTES:
        raise ValueError("missing or oversized JSON manifest")
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict) or type(data.get("documents")) is not list:
        raise ValueError("manifest needs documents array")
    if not 1 <= len(data["documents"]) <= 24:
        raise ValueError("manifest needs 1..24 documents")
    return data


def _safe_input_file(base: Path, name: str) -> Path:
    if not isinstance(name, str) or not name or Path(name).is_absolute():
        raise ValueError("document path must be relative to manifest directory")
    absolute = (base / name).resolve()
    if not absolute.is_relative_to(base.resolve()):
        raise ValueError("PDF path must stay inside manifest directory")
    if absolute.suffix.lower() != ".pdf" or not absolute.is_file():
        raise ValueError("manifest references a missing/non-PDF regular file")
    if not 0 < absolute.stat().st_size <= 20_000_000:
        raise ValueError("PDF exceeds permitted per-document size")
    return absolute


def _one(base: Path, item: dict[str, Any]) -> OfflinePdfEdition:
    if not isinstance(item, dict):
        raise ValueError("each manifest document must be an object")
    rights = item.get("rights")
    if not isinstance(rights, dict):
        raise ValueError("each document requires a rights attestation object")
    attested = OfflineRightsAttestation(
        evidence_reference=rights["evidence_reference"],
        reviewed_by=rights["reviewed_by"],
        offline_processing=rights.get("offline_processing", False) is True,
        store_derived=rights.get("store_derived", False) is True,
        read_derived=rights.get("read_derived", False) is True,
        rights_status=rights.get("rights_status", "PENDING"),
    )
    attested.require("process")
    attested.require("read")
    source = FonteWeb(
        fonte_id=item["source_id"],
        url=item["source_url"], dominio_autorizado=item["source_url"].split("/")[2],
        formato="PDF", status_direitos="APROVADA",
        operacoes_permitidas=frozenset({"COLETA"}),
    )
    contract = ContratoPorto(
        porto=item["port_id"], fonte=source,
        modo="PDF_PARANAGUA" if item["port_id"] == "PARANAGUA" else "PDF_ITAQUI",
        data_referencia=date.fromisoformat(item["reference_date"]),
        serie=item.get("series"),
    )
    contract.validar()
    file_path = _safe_input_file(base, item["file"])
    payload = file_path.read_bytes()
    computed_sha = hashlib.sha256(payload).hexdigest()
    expected_sha = item.get("sha256")
    if not isinstance(expected_sha, str) or expected_sha.lower() != computed_sha:
        raise ValueError("manifest SHA-256 differs from local original PDF bytes")
    document = {
        "conteudo": payload, "sha256": computed_sha, "bytes": len(payload),
        "mime": "application/pdf", "fonte_id": source.fonte_id,
        "url": source.url, "capturado_em": item["collected_at"],
    }
    claims = tuple(
        ProgrammeDuvEvidence(**claim)
        for claim in item.get("programme_duv_evidence", ())
    )
    return OfflinePdfEdition(
        contract=contract, document=document, rights=attested,
        published_at=item.get("published_at"),
        publication_evidence_id=item.get("publication_evidence_id"),
        crosswalk_claims=claims,
        independent_crosswalk_reviewed=(
            item.get("independent_crosswalk_reviewed", False) is True
        ),
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("manifest", type=Path, help="Offline JSON manifest")
    parser.add_argument("--as-of", required=True, help="ISO-8601 timestamp with timezone")
    parser.add_argument("--report", type=Path, help="New JSON report path, must not exist")
    parser.add_argument("--db", type=Path, help="SQLite path, only with --commit")
    parser.add_argument("--commit", action="store_true",
                        help="Persist authorized derived programme editions; no raw PDF stored")
    parser.add_argument("--ack-rights", action="store_true",
                        help="Affirm external rights review for processing and derived retention")
    args = parser.parse_args(argv)
    try:
        if args.commit and (args.db is None or not args.ack_rights):
            raise PermissionError("--commit requires --db and --ack-rights")
        if args.db is not None and not args.commit:
            raise ValueError("--db is only allowed with --commit")
        manifest_path = args.manifest.resolve(strict=True)
        data = _manifest(manifest_path)
        entries = tuple(_one(manifest_path.parent, item) for item in data["documents"])
        target = args.db if args.commit else ":memory:"
        with MaritimeStore(target) as store:
            report = run_offline_pdf_batch(
                entries, store=store, as_of=args.as_of, commit=args.commit
            )
        formatted = json.dumps(report, ensure_ascii=False, sort_keys=True,
                               indent=2, allow_nan=False) + "\n"
        if args.report:
            # Never silently replace an audit trail. One new report per run.
            with args.report.open("x", encoding="utf-8") as output:
                output.write(formatted)
        else:
            sys.stdout.write(formatted)
        return 0
    except (OSError, KeyError, TypeError, ValueError, PermissionError) as exc:
        print(json.dumps({
            "status": "BLOCKED_NO_PUBLICATION",
            "reason": str(exc),
            "database_partially_committed": "UNKNOWN_IF_REPORT_OUTPUT_FAILED",
        }, ensure_ascii=False), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
