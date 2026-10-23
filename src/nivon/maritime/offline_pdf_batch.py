"""Single-entry offline batch orchestrator for authorized port programme PDFs.

Full path: acquired PDF bytes -> existing port collector -> PDF bridge ->
programme edition -> atomic SQLite ledger -> as-of revisions -> audit report.
No acquisition, scraping, publishing, AIS or DUV promotion here. Rights
claims are *human attestations*, not cryptographic/legal verification.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any

from nivon.portos_automaticos import ContratoPorto
from .lineup_history import _aware_utc
from .maritime_store import MaritimeStore
from .official_lineup_bridge import bridge_official_pdf_document
from .pdf_programme_ledger import (
    PdfProgrammeEdition, PdfProgrammeLedger, edition_from_pdf_bridge,
)
from .pdf_programme_revisions import compare_pdf_programme_editions
from .programme_duv_evidence import (
    ProgrammeDuvEvidence, assess_programme_duv_evidence,
)


@dataclass(frozen=True)
class OfflineRightsAttestation:
    """Manual rights assertion for the exact local source and intended action."""
    evidence_reference: str
    reviewed_by: str
    offline_processing: bool = False
    store_derived: bool = False
    read_derived: bool = False
    rights_status: str = "PENDING"

    def require(self, action: str) -> None:
        if (self.rights_status != "ATTESTED"
                or not isinstance(self.evidence_reference, str)
                or not self.evidence_reference.strip()
                or not isinstance(self.reviewed_by, str)
                or not self.reviewed_by.strip()):
            raise PermissionError("source rights attestation absent or pending")
        if action == "process" and not self.offline_processing:
            raise PermissionError("offline document processing not attested")
        if action == "write" and not self.store_derived:
            raise PermissionError("derived-data storage not attested")
        if action == "read" and not self.read_derived:
            raise PermissionError("derived-data history access not attested")


@dataclass(frozen=True)
class OfflinePdfEdition:
    contract: ContratoPorto
    document: dict[str, Any]
    rights: OfflineRightsAttestation
    published_at: str | None = None
    publication_evidence_id: str | None = None
    crosswalk_claims: tuple[ProgrammeDuvEvidence, ...] = ()
    independent_crosswalk_reviewed: bool = False


def run_offline_pdf_batch(
    entries: tuple[OfflinePdfEdition, ...], *,
    store: MaritimeStore, as_of: str | datetime,
    commit: bool = False,
) -> dict[str, Any]:
    """Validate all inputs first, then persist with an all-or-nothing commit.

    Dry-run never writes programme editions, even if a db store is supplied.
    Historical reports never assert that programme numbers count vessel calls.
    """
    if not isinstance(store, MaritimeStore):
        raise TypeError("MaritimeStore connection required")
    if not isinstance(entries, tuple) or not 1 <= len(entries) <= 24:
        raise ValueError("batch must contain between 1 and 24 PDF editions")
    cutoff = _aware_utc(as_of, "as_of")
    prepared: list[tuple[OfflinePdfEdition, PdfProgrammeEdition, dict[str, Any]]] = []
    total_pdf_bytes = 0
    for entry in entries:
        if not isinstance(entry, OfflinePdfEdition):
            raise TypeError("invalid offline PDF batch entry")
        entry.rights.require("process")
        entry.rights.require("read")
        if commit:
            entry.rights.require("write")
        if entry.contract.modo not in {"PDF_ITAQUI", "PDF_PARANAGUA"}:
            raise ValueError("batch accepts only pilot port PDF parsers")
        raw = entry.document.get("conteudo")
        if not isinstance(raw, bytes):
            raise ValueError("original PDF bytes required")
        total_pdf_bytes += len(raw)
        if not 0 < len(raw) <= 20_000_000 or total_pdf_bytes > 80_000_000:
            raise ValueError("PDF bytes exceed offline batch resource limit")
        bridge = bridge_official_pdf_document(
            contract=entry.contract, document=entry.document,
        )
        version = edition_from_pdf_bridge(
            bridge, reference_date=entry.contract.data_referencia.isoformat(),
            competence=entry.contract.data_referencia.isoformat()[:7],
            published_at=entry.published_at,
            publication_evidence_id=entry.publication_evidence_id,
        )
        audit: dict[str, Any] = {
            "port_id": version.port_id, "source_id": version.source_id,
            "series": version.series, "reference_date": version.reference_date,
            "collected_at": version.collected_utc.isoformat(),
            "published_at": version.published_utc.isoformat() if version.published_utc else None,
            "publication_evidence_id": version.publication_evidence_id,
            "source_url": version.source_url,
            "sha256": version.source_sha256,
            "programme_rows": version.source_rows,
            "excluded_as_port_call": version.excluded_call_rows,
            "programme_numbers_declared": len({
                row.programme_number for row in version.rows if row.programme_number
            }),
            "source_rights_reference": entry.rights.evidence_reference,
            "rights_claim": "MANUALLY_ATTESTED_NOT_EXTERNALLY_VERIFIED",
            "document_known_as_of": (
                version.published_utc is not None
                and version.published_utc <= cutoff
                and version.collected_utc <= cutoff
            ),
            "evidence_class": "PROGRAMME_REFERENCE_NOT_PORT_CALL",
            "publishable": False,
        }
        if entry.crosswalk_claims:
            crosswalk = assess_programme_duv_evidence(
                version, entry.crosswalk_claims, as_of=cutoff,
                source_rights_reviewed=(entry.rights.rights_status == "ATTESTED"),
                independent_relation_reviewed=entry.independent_crosswalk_reviewed,
            )
            audit["duv_documentary_candidate"] = crosswalk.summary()
        prepared.append((entry, version, audit))

    ledger = PdfProgrammeLedger(store)
    # All decoding/parsing, SHA, date and rights checks have already succeeded.
    # The transactional helper performs a second canonical validation and
    # rolls back earlier insertions on a later SQLite conflict.
    writes = (
        ledger.save_batch(tuple(version for _, version, _ in prepared),
                          storage_authorized=True)
        if commit else {"inserted": 0, "already_present": 0}
    )
    scopes = sorted({(v.port_id, v.source_id, v.series or "")
                    for _, v, _ in prepared})
    revision_reports: list[dict[str, Any]] = []
    for port_id, source_id, series_key in scopes:
        series = series_key or None
        known_existing = ledger.history_asof(
            port_id=port_id, source_id=source_id, series=series,
            as_of=cutoff, read_authorized=True,
        )
        if commit:
            known = list(known_existing)
        else:
            staged = [
                version for _, version, _ in prepared
                if (version.port_id, version.source_id, version.series or "") ==
                   (port_id, source_id, series_key)
                and version.published_utc is not None
                and version.published_utc <= cutoff and version.collected_utc <= cutoff
            ]
            # Dry-run may use existing authorized history but MUST NOT mutate
            # or accept conflicting editions at the same collection instant.
            index: dict[str, PdfProgrammeEdition] = {
                existing.collected_utc.isoformat(): existing for existing in known_existing
            }
            for version in staged:
                stamp = version.collected_utc.isoformat()
                previous = index.get(stamp)
                if previous is not None and (
                    PdfProgrammeLedger._canonical(previous)[1:]
                    != PdfProgrammeLedger._canonical(version)[1:]
                ):
                    raise ValueError("dry-run conflicts with previously stored programme edition")
                index[stamp] = version
            known = sorted(index.values(), key=lambda item: item.collected_utc)
        for older, newer in zip(known, known[1:]):
            baseline = {
                "port_id": port_id, "source_id": source_id, "series": series,
                "earlier_document_sha256": older.source_sha256,
                "later_document_sha256": newer.source_sha256,
                "earlier_collected_at": older.collected_utc.isoformat(),
                "later_collected_at": newer.collected_utc.isoformat(),
            }
            if older.reference_date != newer.reference_date:
                revision_reports.append({
                    **baseline, "status": "REFERENCE_DATE_BOUNDARY_NO_ID_CONTINUITY",
                    "changes": None, "change_count": None,
                    "physical_operation_claimed": False,
                })
                continue
            changes = compare_pdf_programme_editions(older, newer)
            revision_reports.append({
                **baseline, "status": "PROGRAMME_REVISION_ONLY",
                "source_document_changed": (
                    older.source_sha256.lower() != newer.source_sha256.lower()
                ),
                "change_count": len(changes),
                "changes": [item.summary() for item in changes],
                "physical_operation_claimed": False,
            })
    result = {
        "state": "OFFLINE_DERIVED_REPORT_UNRELEASED",
        "execution_mode": "PERSIST_AUTHORIZED_DERIVED_ONLY" if commit else "DRY_RUN_NO_STORAGE",
        "as_of": cutoff.isoformat(),
        "documents_processed": len(prepared),
        "document_bytes_processed": total_pdf_bytes,
        "edition_writes": writes,
        "documents": [audit for _, _, audit in prepared],
        "revisions": revision_reports,
        "port_call_count": None,
        "realized_tonnes": None,
        "arrivals_confirmed": None,
        "canonical_duv_links_allowed": False,
        "publication_allowed": False,
        "external_rights_verified_by_software": False,
        "source_homologation_status": "NOT_HOMOLOGATED",
    }
    return result
