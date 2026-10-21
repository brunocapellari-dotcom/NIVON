"""Fail-closed, offline intake audit for real *candidate* port line-up editions.

No network, data acquisition, license inference, automatic homologation or
publication. This gate verifies supplied bytes, typed vintage metadata and
per-operation evidence before independent source/legal review.
"""
from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from datetime import datetime
from typing import Iterable
from urllib.parse import urlsplit, unquote

from nivon.portos_automaticos import MODOS, PORTO_HOSTS
from .lineup_history import LineupVintage, _aware_utc


PILOT_PORTS = frozenset((
    "SANTOS", "PARANAGUA", "ITAQUI", "SANTAREM", "BARCARENA_VILA_DO_CONDE"
))
OPERATIONS_FOR_INTERNAL_REVIEW = frozenset((
    "COLLECT", "STORE", "INTERNAL_ANALYSIS"
))
MAX_DOCUMENT_BYTES = 30_000_000
MIN_INDEPENDENT_EDITIONS = 3


@dataclass(frozen=True)
class PilotSource:
    port_id: str
    source_id: str
    mode: str
    registered_url: str
    series: str | None = None

    def __post_init__(self) -> None:
        if self.port_id not in PILOT_PORTS or MODOS.get(self.port_id) != self.mode:
            raise ValueError("unsupported port/parser pair")
        if not self.source_id or not self.source_id.strip():
            raise ValueError("source_id required")
        _validate_url(self.registered_url, self.port_id)
        if self.mode.startswith("PDF") and not self.registered_url.endswith("/"):
            raise ValueError("PDF registered URL prefix must end in slash")
        if self.mode.startswith("HTML") and urlsplit(self.registered_url).path in {"", "/"}:
            raise ValueError("HTML registered URL must identify the exact document endpoint")
        if self.port_id == "PARANAGUA" and self.series not in {
            "EXPORT_OESTE", "EXPORT_LESTE", "IMPORT_SOLIDOS"
        }:
            raise ValueError("Paranagua requires canonical series")
        if self.port_id != "PARANAGUA" and self.series is not None:
            raise ValueError("series only supported for Paranagua")


@dataclass(frozen=True)
class OperationRights:
    """Auditable assertion; never itself grants legal rights.

    VERIFIED must be backed by a real, independently checked authorization
    covering *this port and this exact source*; no wildcard or inferred rights.
    """
    port_id: str
    source_id: str
    operations: frozenset[str]
    evidence_id: str
    reviewed_by: str
    checked_at: str
    expires_at: str | None = None
    status: str = "PENDING"

    def __post_init__(self) -> None:
        if not self.port_id or not self.source_id or not self.evidence_id.strip() or not self.reviewed_by.strip():
            raise ValueError("rights metadata incomplete")
        if self.status not in {"PENDING", "VERIFIED", "DENIED"}:
            raise ValueError("invalid rights status")
        if not self.operations.issubset({
            "COLLECT", "STORE", "INTERNAL_ANALYSIS", "PUBLISH", "REDISTRIBUTE", "BACKUP"
        }):
            raise ValueError("unknown rights operation")
        checked = _aware_utc(self.checked_at, "checked_at")
        if self.expires_at is not None and _aware_utc(self.expires_at, "expires_at") <= checked:
            raise ValueError("rights expiry precedes verification")


@dataclass(frozen=True)
class EditionEvidence:
    """Bytes are supplied by an authorized upstream acquisition, never fetched.

    The number of source rows refers to **eligible schedule rows**, excluding
    operational statuses in mixed PDF documents. Coverage is not inferred from
    a successful parser run. Parser/identity review IDs are independent checks.
    """
    vintage: LineupVintage
    document_bytes: bytes
    source_url: str
    mime: str
    parser_mode: str
    eligible_source_rows: int
    rejected_eligible_rows: int
    parser_review_id: str | None = None
    identity_review_id: str | None = None
    acquisition_evidence_id: str | None = None
    evidence_kind: str = "UNVERIFIED"
    series: str | None = None


@dataclass(frozen=True)
class SourceHomologation:
    port_id: str
    source_id: str
    series: str | None
    status: str
    valid_editions: int
    required_editions: int
    blockers: tuple[str, ...]
    release_allowed: bool = False

    def to_dict(self) -> dict[str, object]:
        return {
            "port_id": self.port_id, "source_id": self.source_id,
            "series": self.series, "status": self.status,
            "valid_editions": self.valid_editions,
            "required_editions": self.required_editions,
            "blockers": list(self.blockers),
            "release_allowed": False,
        }


@dataclass(frozen=True)
class PortfolioHomologation:
    status: str
    sources: tuple[SourceHomologation, ...]
    missing_pilot_ports: tuple[str, ...]
    release_allowed: bool = False

    def to_dict(self) -> dict[str, object]:
        return {
            "status": self.status,
            "sources": [entry.to_dict() for entry in self.sources],
            "missing_pilot_ports": list(self.missing_pilot_ports),
            "release_allowed": False,
        }


def _validate_url(url: str, port_id: str) -> None:
    if not isinstance(url, str) or not url.strip():
        raise ValueError("missing document source URL")
    try:
        parsed = urlsplit(url)
        host, port = parsed.hostname, parsed.port
    except ValueError as exc:
        raise ValueError("invalid source URL") from exc
    decoded_path = unquote(parsed.path)
    if (parsed.scheme != "https" or host not in PORTO_HOSTS[port_id]
            or parsed.username is not None or parsed.password is not None
            or port is not None or parsed.fragment or not parsed.path.startswith("/")
            or any(segment in {".", ".."} for segment in decoded_path.split("/"))
            or "\\" in decoded_path):
        raise ValueError("source URL not within registered authority host")


def audit_edition(edition: EditionEvidence, plan: PilotSource) -> tuple[str, ...]:
    """Return stable issue codes; never trust synthetic labels as approval."""
    v = edition.vintage
    issues: set[str] = set()
    if v.port_id != plan.port_id or v.source_id != plan.source_id:
        issues.add("SOURCE_SCOPE_MISMATCH")
    if edition.parser_mode != plan.mode or edition.series != plan.series:
        issues.add("PARSER_CONTRACT_MISMATCH")
    try:
        _validate_url(edition.source_url, plan.port_id)
        if plan.mode.startswith("HTML"):
            if edition.source_url != plan.registered_url:
                issues.add("URL_NOT_REGISTERED_FOR_SOURCE")
        elif not edition.source_url.startswith(plan.registered_url):
            issues.add("URL_NOT_REGISTERED_FOR_SOURCE")
    except ValueError:
        issues.add("UNVERIFIED_OFFICIAL_URL")
    if not isinstance(edition.document_bytes, bytes) or not (
        0 < len(edition.document_bytes) <= MAX_DOCUMENT_BYTES
    ):
        issues.add("INVALID_DOCUMENT_BYTES")
    else:
        if hashlib.sha256(edition.document_bytes).hexdigest() != v.source_sha256.lower():
            issues.add("DOCUMENT_HASH_MISMATCH")
        if plan.mode.startswith("PDF"):
            if edition.mime != "application/pdf" or not edition.document_bytes.startswith(b"%PDF-"):
                issues.add("PDF_MIME_SIGNATURE_MISMATCH")
        elif (edition.mime not in {"text/html", "application/xhtml+xml"}
              or b"<" not in edition.document_bytes[:512]):
            issues.add("HTML_MIME_SIGNATURE_MISMATCH")
    if v.published_utc is None or not v.publication_evidence_id:
        issues.add("PUBLICATION_UNPROVEN")
    if v.reference_date > v.collected_utc.date().isoformat():
        issues.add("REFERENCE_DATE_AFTER_COLLECTION")
    if (not isinstance(edition.eligible_source_rows, int)
            or type(edition.eligible_source_rows) is bool
            or not isinstance(edition.rejected_eligible_rows, int)
            or type(edition.rejected_eligible_rows) is bool
            or edition.eligible_source_rows <= 0
            or edition.rejected_eligible_rows < 0
            or edition.eligible_source_rows != len(v.calls) + edition.rejected_eligible_rows):
        issues.add("INCOMPLETE_SCHEDULE_ROW_ACCOUNTING")
    elif edition.rejected_eligible_rows:
        issues.add("PARTIAL_SCHEDULE_EXTRACTION")
    if not edition.parser_review_id or not edition.parser_review_id.strip():
        issues.add("PARSER_NOT_REVIEWED")
    if not edition.identity_review_id or not edition.identity_review_id.strip():
        issues.add("CALL_IDENTITY_NOT_REVIEWED")
    if not edition.acquisition_evidence_id or not edition.acquisition_evidence_id.strip():
        issues.add("ACQUISITION_UNPROVEN")
    if edition.evidence_kind != "OFFICIAL_CANDIDATE":
        issues.add("NOT_REAL_OFFICIAL_CANDIDATE")
    return tuple(sorted(issues))


def _rights_gaps(
    rights: Iterable[OperationRights], plan: PilotSource, cutoff: datetime
) -> set[str]:
    matched = [r for r in rights if r.port_id == plan.port_id and r.source_id == plan.source_id]
    if not matched:
        return {"RIGHTS_RECORD_MISSING"}
    # An explicit denial is a hard conflict. Do not let another record
    # silently union permissions over a still-effective rejection.
    if any(
        r.status == "DENIED"
        and _aware_utc(r.checked_at, "checked_at") <= cutoff
        and (r.expires_at is None or _aware_utc(r.expires_at, "expires_at") >= cutoff)
        for r in matched
    ):
        return {"RIGHTS_EXPLICITLY_DENIED"}
    verified = [
        r for r in matched
        if r.status == "VERIFIED"
        and _aware_utc(r.checked_at, "checked_at") <= cutoff
        and (r.expires_at is None or _aware_utc(r.expires_at, "expires_at") >= cutoff)
    ]
    if not verified:
        return {"RIGHTS_NOT_VERIFIED_OR_EXPIRED"}
    available = frozenset().union(*(r.operations for r in verified))
    return {"RIGHTS_" + op + "_MISSING" for op in sorted(OPERATIONS_FOR_INTERNAL_REVIEW - available)}


def audit_source(
    plan: PilotSource, editions: Iterable[EditionEvidence],
    rights: Iterable[OperationRights], *,
    as_of: str | datetime, min_editions: int = MIN_INDEPENDENT_EDITIONS,
) -> SourceHomologation:
    """A passing result is only a dossier ready for **independent review**."""
    if min_editions < MIN_INDEPENDENT_EDITIONS:
        raise ValueError("minimum independently collected editions is three")
    cutoff = _aware_utc(as_of, "as_of")
    problems = _rights_gaps(rights, plan, cutoff)
    valid_keys: set[tuple[str, str]] = set()
    all_hashes: set[str] = set()
    all_stamps: set[str] = set()
    for edition in editions:
        # Do not allow a document from another authority to satisfy this plan.
        if edition.vintage.port_id != plan.port_id or edition.vintage.source_id != plan.source_id:
            problems.add("SOURCE_SCOPE_MISMATCH")
            continue
        fingerprint = edition.vintage.source_sha256.lower()
        stamp = edition.vintage.collected_utc.isoformat()
        errors = audit_edition(edition, plan)
        if edition.vintage.collected_utc > cutoff or (
            edition.vintage.published_utc is not None
            and edition.vintage.published_utc > cutoff
        ):
            problems.add("FUTURE_EVIDENCE_IN_AUDIT")
            continue
        if errors:
            problems.update(errors)
            continue
        if stamp in all_stamps:
            problems.add("DUPLICATE_COLLECTION_INSTANT")
        if fingerprint in all_hashes:
            problems.add("REUSED_DOCUMENT_ACROSS_EDITIONS")
        all_stamps.add(stamp)
        all_hashes.add(fingerprint)
        valid_keys.add((stamp, fingerprint))
    if len(valid_keys) < min_editions:
        problems.add("INSUFFICIENT_INDEPENDENT_EDITIONS")
    return SourceHomologation(
        port_id=plan.port_id, source_id=plan.source_id, series=plan.series,
        status="READY_FOR_INDEPENDENT_REVIEW" if not problems else "BLOCKED",
        valid_editions=len(valid_keys), required_editions=min_editions,
        blockers=tuple(sorted(problems)),
    )


def audit_pilot_portfolio(
    plans: Iterable[PilotSource], editions: Iterable[EditionEvidence],
    rights: Iterable[OperationRights], *, as_of: str | datetime,
) -> PortfolioHomologation:
    plan_rows = tuple(plans)
    evidence_rows = tuple(editions)
    rights_rows = tuple(rights)
    keys = [(plan.port_id, plan.source_id, plan.series) for plan in plan_rows]
    if len(keys) != len(set(keys)):
        raise ValueError("duplicate pilot plan")
    covered = {plan.port_id for plan in plan_rows}
    missing = tuple(sorted(PILOT_PORTS - covered))
    sources = tuple(audit_source(
        plan, (e for e in evidence_rows if e.vintage.port_id == plan.port_id
               and e.vintage.source_id == plan.source_id and e.series == plan.series),
        rights_rows, as_of=as_of,
    ) for plan in plan_rows)
    status = (
        "READY_FOR_INDEPENDENT_REVIEW"
        if not missing and sources and all(s.status == "READY_FOR_INDEPENDENT_REVIEW" for s in sources)
        else "BLOCKED"
    )
    return PortfolioHomologation(status=status, sources=sources, missing_pilot_ports=missing)
