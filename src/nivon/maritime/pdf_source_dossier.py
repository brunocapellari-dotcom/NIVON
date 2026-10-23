"""Per-authority source-readiness dossier from offline PDF programme editions.

This is NOT a legally verified licence, authority-certified PDF or release.
It makes missing original editions, publication evidence, DUV identity and
external visual review explicit in the batch's existing JSON report.
No network, no automatic rights elevation, no new data storage.
"""
from __future__ import annotations

from collections import defaultdict
from datetime import datetime

from .lineup_history import _aware_utc
from .pdf_programme_ledger import PdfProgrammeEdition

MIN_INDEPENDENT_EDITIONS = 3


def source_readiness_dossiers(
    editions: tuple[PdfProgrammeEdition, ...], *,
    as_of: str | datetime,
) -> list[dict[str, object]]:
    """Group by exact (port, source, series), and fail closed on outside facts.

    "Independence" means only distinct source bytes and collection instants
    observed within the same scope, not independent review or provenance.
    The same original bytes collected three times still counts as ONE.
    Edições conhecidas after the given cutoff are excluded from counts.
    """
    cutoff = _aware_utc(as_of, "as_of")
    scopes: dict[tuple[str, str, str], list[PdfProgrammeEdition]] = defaultdict(list)
    for edition in editions:
        if not isinstance(edition, PdfProgrammeEdition):
            raise TypeError("requires typed programme editions")
        scopes[(edition.port_id, edition.source_id, edition.series or "")].append(edition)
    result: list[dict[str, object]] = []
    for port_id, source_id, series_key in sorted(scopes):
        received = scopes[(port_id, source_id, series_key)]
        eligible = [
            edition for edition in received
            if edition.published_utc is not None
            and edition.published_utc <= cutoff
            and edition.collected_utc <= cutoff
        ]
        source_sha = {e.source_sha256.lower() for e in eligible}
        collection_stamps = {e.collected_utc.isoformat() for e in eligible}
        unique_editions = min(len(source_sha), len(collection_stamps))
        unverified_rows = sum(e.excluded_call_rows for e in eligible)
        distinct_programmes = {
            (e.reference_date, row.programme_number)
            for e in eligible for row in e.rows if row.programme_number
        }
        declared_duv_rows = sum(
            1 for e in eligible for row in e.rows if row.explicit_duv
        )
        issues: set[str] = {
            "EXTERNAL_RIGHTS_VERIFICATION_REQUIRED",
            "ORIGINAL_PDF_VISUAL_PAGE_AUDIT_REQUIRED",
            "OFFICIAL_PUBLISHER_AUTHENTICITY_NOT_VERIFIED",
            "OPERATIONAL_RELEASE_NOT_AUTHORIZED",
        }
        if not eligible:
            issues.add("NO_EDITION_WITH_VERIFIABLE_ASOF_PUBLICATION")
        if len(received) != len(eligible):
            issues.add("SOME_EDITIONS_UNKNOWN_OR_FUTURE_AT_ASOF")
        if unique_editions < MIN_INDEPENDENT_EDITIONS:
            issues.add("FEWER_THAN_THREE_DISTINCT_DATED_EDITIONS")
        if len(source_sha) != len(eligible):
            issues.add("REUSED_DOCUMENT_BYTES_NOT_INDEPENDENT")
        if len(collection_stamps) != len(eligible):
            issues.add("DUPLICATED_COLLECTION_INSTANT")
        if unverified_rows:
            issues.add("PDF_ROWS_NOT_ELIGIBLE_AS_PORT_CALLS")
        if not declared_duv_rows:
            issues.add("NO_EXPLICIT_DUV_IN_KNOWN_PDF_EDITION")
        if len({e.reference_date for e in eligible}) > 1:
            issues.add("CROSS_REFERENCE_DATE_PROGRAMME_ID_NOT_PROVEN_STABLE")
        result.append({
            "port_id": port_id,
            "source_id": source_id,
            "series": series_key or None,
            "as_of": cutoff.isoformat(),
            "documents_supplied": len(received),
            "documents_known_as_of": len(eligible),
            "distinct_source_hashes_known_as_of": len(source_sha),
            "distinct_collection_instants_known_as_of": len(collection_stamps),
            "distinct_edition_count_for_review": unique_editions,
            "min_distinct_editions_for_review": MIN_INDEPENDENT_EDITIONS,
            "source_rows_known_as_of": sum(e.source_rows for e in eligible),
            "rows_excluded_from_port_call_identity": unverified_rows,
            "programme_references_scoped_by_reference_date": len(distinct_programmes),
            "explicit_duv_row_occurrences": declared_duv_rows,
            "document_set_has_three_distinct_known_editions": (
                unique_editions >= MIN_INDEPENDENT_EDITIONS
            ),
            "status": "NOT_HOMOLOGATED_EXTERNAL_REVIEW_REQUIRED",
            "blockers": sorted(issues),
            "release_allowed": False,
            "verified_rights_from_software": False,
            "confirmed_port_call_count": None,
            "realized_tonnes": None,
            "evidence_class": "PDF_PROGRAMME_SOURCE_AUDIT_NOT_OFFICIAL_APPROVAL",
        })
    return result
