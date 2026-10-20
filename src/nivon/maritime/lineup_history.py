"""Versioned, strictly as-of official line-up snapshots. No network or storage.

A port schedule is an authority's PROGRAMMED/DECLARED statement. Its absence,
revision, or reported status cannot attest to a performed operation or tonnage.
Publication evidence and collection times are separate non-imputable gates.
"""
from __future__ import annotations

import hashlib
import math
import re
from dataclasses import dataclass
from datetime import date, datetime, timezone
from typing import Iterable

from .shipping_reconciliation import LineupCall


def _aware_utc(value: datetime | str, label: str) -> datetime:
    try:
        parsed = value if isinstance(value, datetime) else datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (ValueError, TypeError) as exc:
        raise ValueError(f"{label}: invalid timestamp") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError(f"{label}: timezone required")
    return parsed.astimezone(timezone.utc)


def _period(value: str) -> str:
    if not re.fullmatch(r"\d{4}-\d{2}", value):
        raise ValueError("competencia must be YYYY-MM")
    try:
        date.fromisoformat(value + "-01")
    except ValueError as exc:
        raise ValueError("invalid competencia") from exc
    return value


@dataclass(frozen=True)
class LineupVintage:
    """Immutable acquisition, not a cargo movement.

    An edition with no proven publication date may be retained for audit but
    is not eligible for historical as-of selection.
    """

    port_id: str
    source_id: str
    source_sha256: str
    collected_at: datetime | str
    reference_date: str
    competence: str
    calls: tuple[LineupCall, ...]
    published_at: datetime | str | None = None
    publication_evidence_id: str | None = None

    def __post_init__(self) -> None:
        if not self.port_id or not self.port_id.strip() or not self.source_id or not self.source_id.strip():
            raise ValueError("port_id and source_id required")
        if not re.fullmatch(r"[0-9a-fA-F]{64}", self.source_sha256):
            raise ValueError("source_sha256 must be SHA-256 hex")
        collected = _aware_utc(self.collected_at, "collected_at")
        if len(self.reference_date) != 10:
            raise ValueError("reference_date must be YYYY-MM-DD")
        try:
            date.fromisoformat(self.reference_date)
        except ValueError as exc:
            raise ValueError("invalid reference_date") from exc
        _period(self.competence)
        has_publication = self.published_at is not None
        has_evidence = bool(self.publication_evidence_id and self.publication_evidence_id.strip())
        if has_publication != has_evidence:
            raise ValueError("publication timestamp and publication evidence must appear together")
        if has_publication and _aware_utc(self.published_at, "published_at") > collected:
            raise ValueError("publication cannot occur after collection")

        identities: set[str] = set()
        for call in self.calls:
            if (not call.call_id or not call.call_id.strip() or call.call_id in identities):
                raise ValueError("duplicate or blank call_id in lineup vintage")
            identities.add(call.call_id)
            if call.port_id.strip().upper() != self.port_id.strip().upper():
                raise ValueError("lineup call from another port")
            if call.source_id != self.source_id:
                raise ValueError("lineup call from another source")
            if _aware_utc(call.collected_at, "call.collected_at") != collected:
                raise ValueError("lineup call belongs to another collection vintage")
            _aware_utc(call.eta, "call.eta")
            volume = call.planned_volume_t
            if volume is not None and (not math.isfinite(volume) or volume < 0):
                raise ValueError("invalid planned tonnage")

    @property
    def collected_utc(self) -> datetime:
        return _aware_utc(self.collected_at, "collected_at")

    @property
    def published_utc(self) -> datetime | None:
        return _aware_utc(self.published_at, "published_at") if self.published_at is not None else None

    def provenance(self) -> dict[str, str | None]:
        return {
            "port_id": self.port_id,
            "source_id": self.source_id,
            "source_sha256": self.source_sha256.lower(),
            "competencia": self.competence,
            "data_referencia": self.reference_date,
            "data_publicacao": self.published_utc.isoformat() if self.published_utc else None,
            "data_coleta": self.collected_utc.isoformat(),
            "publication_evidence_id": self.publication_evidence_id,
            "evidence_class": "LINEUP_DECLARED_NOT_REALIZED",
        }


@dataclass(frozen=True)
class LineupAsOf:
    status: str
    as_of: str
    port_id: str
    source_id: str
    snapshot: LineupVintage | None
    # Null denotes missing evidence. An empty tuple denotes a verified empty
    # schedule edition, which is NOT proof of zero vessels in the port.
    programmed_calls: tuple[LineupCall, ...] | None

    def summary(self) -> dict[str, object]:
        return {
            "status": self.status,
            "as_of": self.as_of,
            "port_id": self.port_id,
            "source_id": self.source_id,
            "programmed_call_count": len(self.programmed_calls) if self.programmed_calls is not None else None,
            "operated_call_count": None,
            "realized_volume_t": None,
            "snapshot_provenance": self.snapshot.provenance() if self.snapshot else None,
            "publication_allowed": False,
        }


def select_lineup_asof(
    vintages: Iterable[LineupVintage], *,
    as_of: datetime | str,
    port_id: str,
    source_id: str,
) -> LineupAsOf:
    """Pick the most recently collected eligible version, never future evidence.

    Each source is queried separately: versions from independent ports/sources
    are not merged, and their similar ship names cannot become one visit.
    """
    cutoff = _aware_utc(as_of, "as_of")
    if not port_id or not port_id.strip() or not source_id or not source_id.strip():
        raise ValueError("port_id and source_id required")
    eligible = [
        item for item in vintages
        if item.port_id.strip().upper() == port_id.strip().upper()
        and item.source_id == source_id
        and item.published_utc is not None
        and item.published_utc <= cutoff
        and item.collected_utc <= cutoff
    ]
    if not eligible:
        return LineupAsOf("DATA_GATED", cutoff.isoformat(), port_id, source_id, None, None)
    newest_time = max(item.collected_utc for item in eligible)
    newest = [item for item in eligible if item.collected_utc == newest_time]
    # A same-instant competing edition requires human source arbitration; never
    # choose by sorting checksum or information that arrived later.
    hashes = {item.source_sha256.lower() for item in newest}
    if len(hashes) != 1:
        raise ValueError("conflicting lineup snapshots at same collection instant")
    if len({(item.published_utc, item.publication_evidence_id, item.reference_date, item.competence) for item in newest}) != 1:
        raise ValueError("contradictory metadata for identical lineup snapshot")
    snapshot = newest[0]
    return LineupAsOf(
        "PROGRAMMED_SNAPSHOT_ONLY", cutoff.isoformat(),
        port_id, source_id, snapshot, snapshot.calls,
    )


@dataclass(frozen=True)
class LineupChange:
    call_id: str
    field: str
    before: str | float | None
    after: str | float | None
    classification: str = "LINEUP_REVISION_NOT_CONFIRMED_OPERATION"


def compare_lineup_vintages(previous: LineupVintage, current: LineupVintage) -> tuple[LineupChange, ...]:
    """Revision ledger: disappearance or declared completion is not realization."""
    if previous.port_id.strip().upper() != current.port_id.strip().upper() or previous.source_id != current.source_id:
        raise ValueError("lineup vintages must share source and port")
    if previous.collected_utc >= current.collected_utc:
        raise ValueError("current vintage must be collected later")
    before = {call.call_id: call for call in previous.calls}
    after = {call.call_id: call for call in current.calls}
    changes: list[LineupChange] = []
    for call_id in sorted(before.keys() | after.keys()):
        old, new = before.get(call_id), after.get(call_id)
        if old is None:
            changes.append(LineupChange(call_id, "new_programmed_call", None, "PROGRAMMED"))
        elif new is None:
            changes.append(LineupChange(call_id, "absent_from_new_snapshot_unconfirmed", "PRESENT", None))
        else:
            fields = (
                ("eta", old.eta_utc.isoformat(), new.eta_utc.isoformat()),
                ("planned_volume_t", old.planned_volume_t, new.planned_volume_t),
                ("terminal_id", old.terminal_id, new.terminal_id),
                ("product", old.product, new.product),
                ("lineup_status_declared", old.lineup_status, new.lineup_status),
                ("imo", old.imo, new.imo),
                ("mmsi", old.mmsi, new.mmsi),
            )
            for name, prior, updated in fields:
                if prior != updated:
                    changes.append(LineupChange(call_id, name, prior, updated))
    return tuple(changes)
