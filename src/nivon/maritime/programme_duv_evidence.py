"""Deny-by-default documentary candidate links: N. Prog -> DUV.

A port programme reference is NOT a port call. Only source-scoped, dated,
documented links are candidates for independent verification; this module
never issues a canonical DUV, promotes a LineupVintage, records cargo as
performed, fetches documents or releases data. Self-declared reviewer IDs
and hashes are not signatures or proof of third-party authority.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime
from urllib.parse import urlsplit

from nivon.portos_automaticos import PORTO_HOSTS
from .lineup_history import _aware_utc
from .pdf_programme_ledger import PdfProgrammeEdition


DUV_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.:/-]{0,127}\Z")
SHA_RE = re.compile(r"[a-fA-F0-9]{64}\Z")
DIRECT_EVIDENCE_KINDS = frozenset({
    "OFFICIAL_SOURCE_EXPLICIT_PAIR",
    "OFFICIAL_AUTHORITY_CROSSWALK",
})
# This is an evidence intake, not a list of permitted web scrapers or
# a licensing declaration. Only paths/hosts explicitly declared for a
# particular evidence kind may be provided. No network calls.
OFFICIAL_PSP_HOSTS = frozenset({"concentrador.portosempapel.gov.br"})


@dataclass(frozen=True)
class ProgrammeDuvEvidence:
    """One claimed association, with the complete source + temporal scope.

    The associated PDF edition must exist independently. Association evidence
    must be original and explicitly name *both* programme and DUV, never be
    inferred from shared IMO, ship name, approximate ETA or row positions.
    """
    port_id: str
    source_id: str
    series: str
    reference_date: str
    programme_number: str
    duv: str
    lineup_source_sha256: str
    link_evidence_url: str
    link_document_sha256: str
    link_evidence_id: str
    acquisition_evidence_id: str
    publication_evidence_id: str
    published_at: str | datetime
    acquired_at: str | datetime
    reviewed_at: str | datetime
    reviewed_by: str
    evidence_kind: str = "UNVERIFIED"

    def __post_init__(self) -> None:
        if self.port_id != "PARANAGUA" or not self.source_id.strip():
            raise ValueError("crosswalk supports only explicitly scoped Paranagua source")
        if self.series not in {"EXPORT_OESTE", "EXPORT_LESTE", "IMPORT_SOLIDOS"}:
            raise ValueError("canonical series required")
        if not isinstance(self.programme_number, str) or not self.programme_number.startswith(self.series + ":"):
            raise ValueError("programme number must be scoped to series")
        suffix = self.programme_number.split(":", 1)[1]
        if not suffix or suffix != suffix.strip() or len(suffix) > 128:
            raise ValueError("empty/ambiguous programme number")
        if not isinstance(self.duv, str) or not DUV_RE.fullmatch(self.duv):
            raise ValueError("explicit valid DUV required, never IMO/name as substitute")
        if not SHA_RE.fullmatch(self.lineup_source_sha256) or not SHA_RE.fullmatch(self.link_document_sha256):
            raise ValueError("two original document hashes required")
        if (not self.link_evidence_id.strip() or not self.acquisition_evidence_id.strip()
                or not self.publication_evidence_id.strip() or not self.reviewed_by.strip()):
            raise ValueError("source, acquisition, publication and independent review IDs required")
        if self.evidence_kind not in DIRECT_EVIDENCE_KINDS:
            raise ValueError("direct documentary evidence type required")
        try:
            url = urlsplit(self.link_evidence_url)
            host, port = url.hostname, url.port
        except ValueError as exc:
            raise ValueError("invalid evidence URL") from exc
        allowed = PORTO_HOSTS[self.port_id] | OFFICIAL_PSP_HOSTS
        if (url.scheme != "https" or host not in allowed or port is not None
                or url.username is not None or url.password is not None
                or url.fragment or not url.path.startswith("/")):
            raise ValueError("association evidence URL outside registered authority")
        from datetime import date
        try:
            date.fromisoformat(self.reference_date)
        except (ValueError, TypeError) as exc:
            raise ValueError("valid reference date required") from exc
        published = _aware_utc(self.published_at, "published_at")
        acquired = _aware_utc(self.acquired_at, "acquired_at")
        reviewed = _aware_utc(self.reviewed_at, "reviewed_at")
        if published > acquired or acquired > reviewed:
            raise ValueError("association evidence temporal order invalid")
        if self.evidence_kind == "OFFICIAL_SOURCE_EXPLICIT_PAIR":
            if host not in PORTO_HOSTS[self.port_id]:
                raise ValueError("original PDF pair requires port authority source")
            if self.link_document_sha256.lower() != self.lineup_source_sha256.lower():
                raise ValueError("original PDF pair hash does not match lineup edition")


@dataclass(frozen=True)
class ProgrammeDuvCandidateReport:
    status: str
    port_id: str
    source_id: str
    series: str | None
    reference_date: str
    as_of: str
    candidate_pairs: tuple[tuple[str, str], ...]
    rejected_reasons: tuple[str, ...]
    release_allowed: bool = False
    canonical_duv_link_allowed: bool = False

    def summary(self) -> dict[str, object]:
        return {
            "status": self.status, "port_id": self.port_id,
            "source_id": self.source_id, "series": self.series,
            "reference_date": self.reference_date, "as_of": self.as_of,
            "candidate_pairs": [
                {"programme_number": programme, "duv_candidate": duv}
                for programme, duv in self.candidate_pairs
            ],
            "rejected_reasons": list(self.rejected_reasons),
            "release_allowed": False,
            "canonical_duv_link_allowed": False,
            "evidence_class": "DOCUMENTARY_CANDIDATE_NOT_VERIFIED_PORT_CALL",
        }


def assess_programme_duv_evidence(
    edition: PdfProgrammeEdition,
    evidences: tuple[ProgrammeDuvEvidence, ...],
    *, as_of: str | datetime,
    source_rights_reviewed: bool = False,
    independent_relation_reviewed: bool = False,
) -> ProgrammeDuvCandidateReport:
    """Build an *unapproved* crosswalk dossier; never mutate canonical ledgers.

    If any evidence is out of scope or conflicts, fail closed rather than
    quietly selecting the plausible link. A string review flag documents
    upstream work but does not grant source licenses.
    """
    if not isinstance(edition, PdfProgrammeEdition) or edition.port_id != "PARANAGUA":
        raise ValueError("requires Paranagua PDF programme edition")
    if not isinstance(evidences, tuple) or any(
        not isinstance(item, ProgrammeDuvEvidence) for item in evidences
    ):
        raise TypeError("requires typed tuple of documentary evidence")
    cutoff = _aware_utc(as_of, "as_of")
    blockers: set[str] = set()
    if not source_rights_reviewed:
        blockers.add("SOURCE_RIGHTS_UNREVIEWED")
    if not independent_relation_reviewed:
        blockers.add("RELATION_NOT_INDEPENDENTLY_REVIEWED")
    if edition.published_utc is None:
        blockers.add("PROGRAMME_EDITION_PUBLICATION_UNPROVEN")
    if edition.collected_utc > cutoff or (
        edition.published_utc is not None and edition.published_utc > cutoff
    ):
        blockers.add("PROGRAMME_EDITION_FUTURE_ASOF")

    programme_counts: dict[str, int] = {}
    for row in edition.rows:
        if row.programme_number:
            programme_counts[row.programme_number] = programme_counts.get(row.programme_number, 0) + 1
    pairs: dict[str, str] = {}
    conflicts: set[str] = set()
    for evidence in evidences:
        if (evidence.port_id, evidence.source_id, evidence.series, evidence.reference_date,
                evidence.lineup_source_sha256.lower()) != (
            edition.port_id, edition.source_id, edition.series,
            edition.reference_date, edition.source_sha256.lower()
        ):
            blockers.add("DOCUMENT_SCOPE_MISMATCH")
            continue
        if evidence.programme_number not in programme_counts:
            blockers.add("PROGRAMME_NOT_FOUND_IN_EDITION")
            continue
        if (
            _aware_utc(evidence.published_at, "published_at") > cutoff
            or _aware_utc(evidence.acquired_at, "acquired_at") > cutoff
            or _aware_utc(evidence.reviewed_at, "reviewed_at") > cutoff
        ):
            blockers.add("LINK_EVIDENCE_FUTURE_ASOF")
            continue
        if (evidence.evidence_kind == "OFFICIAL_SOURCE_EXPLICIT_PAIR"
                and evidence.link_evidence_url != edition.source_url):
            blockers.add("ORIGINAL_PDF_URL_MISMATCH")
            continue
        earlier = pairs.get(evidence.programme_number)
        if earlier is not None and earlier != evidence.duv:
            conflicts.add(evidence.programme_number)
            blockers.add("CONTRADICTORY_DUV_FOR_SAME_PROGRAMME")
        else:
            pairs[evidence.programme_number] = evidence.duv
    if not evidences:
        blockers.add("LINK_EVIDENCE_MISSING")
    if conflicts:
        # None of the conflicting candidates is eligible for review.
        for programme in conflicts:
            pairs.pop(programme, None)
    # Trusting a self-entered reviewer/evidence ID cannot approve a source.
    # Even an internally clean dossier is only ready for independent review.
    if blockers:
        status = "BLOCKED_UNVERIFIED_DOCUMENTARY_LINK"
        pair_view: tuple[tuple[str, str], ...] = ()
    else:
        status = "CANDIDATE_READY_FOR_EXTERNAL_VERIFICATION"
        pair_view = tuple(sorted(pairs.items()))
    return ProgrammeDuvCandidateReport(
        status=status, port_id=edition.port_id, source_id=edition.source_id,
        series=edition.series, reference_date=edition.reference_date,
        as_of=cutoff.isoformat(), candidate_pairs=pair_view,
        rejected_reasons=tuple(sorted(blockers)),
    )
