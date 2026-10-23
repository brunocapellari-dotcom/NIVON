"""Integration-only Docker fixture and assertions for NIVON maritime PDFs.

Generates *synthetic*, well-formed PDFs with ReportLab; invokes the actual
Docker CLI through CI and verifies dry-run -> atomic commit -> replay. This
script never obtains third-party data and does not grant a source licence.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import sqlite3
import sys

from test_maritime_pdfplumber_e2e import (
    STAMP, itaqui_pdf, local_manifest, paranagua_pdf,
)


def prepare(inputs: Path, outputs: Path) -> None:
    inputs.mkdir(parents=True, exist_ok=True)
    outputs.mkdir(parents=True, exist_ok=True)
    local_manifest(inputs, [
        ("PARANAGUA", paranagua_pdf(duv="", clock="09:00"), STAMP,
         "2026-10-20T11:00:00+00:00"),
        ("PARANAGUA", paranagua_pdf(duv="", clock="11:30"),
         "2026-10-20T16:00:00+00:00", "2026-10-20T15:00:00+00:00"),
        ("ITAQUI", itaqui_pdf(duv=""), STAMP,
         "2026-10-20T11:00:00+00:00"),
    ])
    if (outputs / "maritime.sqlite").exists():
        raise AssertionError("fresh fixture output must not contain SQLite")
    # A *different* command and manifest, later in time, represents the
    # next edition arriving on another collection run (not the first batch).
    later_pdf = paranagua_pdf(duv="", clock="14:45")
    filename = "fixture_incremental.pdf"
    (inputs / filename).write_bytes(later_pdf)
    first = json.loads((inputs / "input_manifest.json").read_text())
    west = dict(first["documents"][0])
    west.update({
        "file": filename,
        "sha256": hashlib.sha256(later_pdf).hexdigest(),
        "collected_at": "2026-10-20T19:00:00+00:00",
        "published_at": "2026-10-20T18:00:00+00:00",
        "publication_evidence_id": "SYNTHETIC_PUB_3",
    })
    (inputs / "incremental_manifest.json").write_text(
        json.dumps({"documents": [west]}), encoding="utf-8"
    )


def assert_report(report: dict, *, mode: str, inserted: int, repeated: int) -> None:
    assert report["execution_mode"] == mode, report
    assert report["documents_processed"] == 3
    assert report["edition_writes"] == {
        "inserted": inserted, "already_present": repeated
    }
    assert len(report["documents"]) == 3
    assert len(report["revisions"]) == 1
    assert report["revisions"][0]["status"] == "PROGRAMME_REVISION_ONLY"
    assert report["revisions"][0]["change_count"] == 1
    assert report["revisions"][0]["changes"][0]["field"] == "eta_text_declared"
    assert report["port_call_count"] is None
    assert report["realized_tonnes"] is None
    assert report["arrivals_confirmed"] is None
    assert report["publication_allowed"] is False
    assert report["canonical_duv_links_allowed"] is False
    assert report["source_homologation_status"] == "NOT_HOMOLOGATED"
    by_port = {row["port_id"]: row for row in report["source_readiness"]}
    assert set(by_port) == {"PARANAGUA", "ITAQUI"}
    assert by_port["PARANAGUA"]["documents_known_as_of"] == 2
    assert by_port["ITAQUI"]["documents_known_as_of"] == 1
    for readiness in by_port.values():
        assert readiness["status"] == "NOT_HOMOLOGATED_EXTERNAL_REVIEW_REQUIRED"
        assert "FEWER_THAN_THREE_DISTINCT_DATED_EDITIONS" in readiness["blockers"]
        assert "NO_EXPLICIT_DUV_IN_KNOWN_PDF_EDITION" in readiness["blockers"]
        assert readiness["release_allowed"] is False
    assert all(
        d["pdf_extraction_mode"] == "ISOLATED_TABLES_PREVALIDATED"
        for d in report["documents"]
    )


def verify(outputs: Path) -> None:
    with (outputs / "audit_dryrun.json").open(encoding="utf-8") as f:
        dry = json.load(f)
    with (outputs / "audit_commit.json").open(encoding="utf-8") as f:
        committed = json.load(f)
    with (outputs / "audit_replay.json").open(encoding="utf-8") as f:
        replay = json.load(f)
    assert_report(dry, mode="DRY_RUN_NO_STORAGE", inserted=0, repeated=0)
    assert_report(committed, mode="PERSIST_AUTHORIZED_DERIVED_ONLY", inserted=3, repeated=0)
    assert_report(replay, mode="PERSIST_AUTHORIZED_DERIVED_ONLY", inserted=0, repeated=3)
    assert dry["revisions"] == committed["revisions"] == replay["revisions"]
    incremental = json.loads((outputs / "audit_incremental.json").read_text())
    rerun_incremental = json.loads(
        (outputs / "audit_incremental_replay.json").read_text()
    )
    assert incremental["edition_writes"] == {"inserted": 1, "already_present": 0}
    assert rerun_incremental["edition_writes"] == {"inserted": 0, "already_present": 1}
    assert incremental["documents_processed"] == 1
    assert incremental["revisions"] == rerun_incremental["revisions"]
    assert len(incremental["revisions"]) == 2
    combined_readiness = incremental["source_readiness"]
    assert len(combined_readiness) == 1
    west = combined_readiness[0]
    assert west["port_id"] == "PARANAGUA"
    assert west["documents_in_current_batch"] == 1
    assert west["persisted_audit_editions_prior_to_batch"] == 2
    assert west["documents_known_as_of"] == 3
    assert west["distinct_edition_count_for_review"] == 3
    assert west["document_set_has_three_distinct_known_editions"] is True
    assert "FEWER_THAN_THREE_DISTINCT_DATED_EDITIONS" not in west["blockers"]
    assert "EXTERNAL_RIGHTS_VERIFICATION_REQUIRED" in west["blockers"]
    assert west["release_allowed"] is False
    assert incremental["publication_allowed"] is False
    assert incremental["port_call_count"] is None
    assert incremental["realized_tonnes"] is None
    with sqlite3.connect(outputs / "maritime.sqlite") as db:
        tables = db.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
        assert ("maritime_pdf_programme_editions",) in tables
        assert db.execute(
            "SELECT COUNT(*) FROM maritime_pdf_programme_editions"
        ).fetchone()[0] == 4
        if ("maritime_lineup_vintages",) in tables:
            assert db.execute(
                "SELECT COUNT(*) FROM maritime_lineup_vintages"
            ).fetchone()[0] == 0
    print("CONTAINER_PDF_E2E_PASS: 3 first-batch editions plus one later edition, "
          "cumulative 3-unique-source readiness, 2 ETA revisions, "
          "dry-run, atomic commit, idempotent replay across two manifests, zero physical claims")


if __name__ == "__main__":
    if len(sys.argv) < 3:
        raise SystemExit("usage: maritime_container_smoke.py prepare IN OUT | verify OUT")
    if sys.argv[1] == "prepare" and len(sys.argv) == 4:
        prepare(Path(sys.argv[2]), Path(sys.argv[3]))
    elif sys.argv[1] == "verify" and len(sys.argv) == 3:
        verify(Path(sys.argv[2]))
    else:
        raise SystemExit("invalid arguments")
