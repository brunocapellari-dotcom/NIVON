# Adapted from AgroLogMT/models/vessel_identity.py (main 2026-10-19); internal use, validate provenance before release.
from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Iterable

from nivon.maritime.ais_quality import normalize_imo, valid_imo, valid_mmsi
from nivon.maritime.shipping_reconciliation import normalize_vessel_name


@dataclass(frozen=True)
class IdentityObservation:
    source_id: str
    observed_at: str
    imo: str | None = None
    mmsi: str | None = None
    vessel_name: str | None = None
    official_registry: bool = False


@dataclass(frozen=True)
class VesselIdentityResolution:
    status: str
    canonical_imo: str | None
    canonical_mmsi: str | None
    canonical_name: str | None
    confidence: float
    conflicts: tuple[str, ...]
    warnings: tuple[str, ...]
    source_ids: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _utc(value: str) -> datetime:
    text = str(value).strip().replace("Z", "+00:00")
    parsed = datetime.fromisoformat(text)
    if parsed.tzinfo is None:
        raise ValueError("identity observed_at deve ter timezone")
    return parsed.astimezone(timezone.utc)


def _clean_mmsi(value: Any) -> str | None:
    text = str(value or "").strip()
    return text if valid_mmsi(text) else None


def _clean_imo(value: Any) -> str | None:
    text = normalize_imo(value)
    return text if text is not None and valid_imo(text) else None


def _recent_mmsi_imo_conflicts(
    observations: list[tuple[IdentityObservation, datetime, str | None, str | None]],
    *,
    conflict_window_days: int,
) -> set[str]:
    conflicts: set[str] = set()
    by_mmsi: dict[str, list[tuple[datetime, str]]] = {}
    for _, at, imo, mmsi in observations:
        if imo and mmsi:
            by_mmsi.setdefault(mmsi, []).append((at, imo))
    window = timedelta(days=max(1, conflict_window_days))
    for mmsi, rows in by_mmsi.items():
        rows.sort(key=lambda item: item[0])
        for index, (left_at, left_imo) in enumerate(rows):
            for right_at, right_imo in rows[index + 1:]:
                if right_at - left_at > window:
                    break
                if left_imo != right_imo:
                    conflicts.add(f"mmsi_recent_multiple_imo:{mmsi}:{left_imo}:{right_imo}")
    return conflicts


def resolve_vessel_identity(
    observations: Iterable[IdentityObservation],
    *,
    conflict_window_days: int = 90,
) -> VesselIdentityResolution:
    """Resolve vessel identity with IMO > MMSI > normalized name.

    A recent MMSI-to-multiple-IMO collision is a hard conflict. Multiple MMSIs for the
    same IMO are retained as a warning because legitimate flag/registry changes can
    occur over time. Fuzzy name matching is deliberately outside this canonical layer.
    """
    rows = list(observations)
    if not rows:
        return VesselIdentityResolution("UNRESOLVED", None, None, None, 0.0, (), (), ())

    prepared: list[tuple[IdentityObservation, datetime, str | None, str | None]] = []
    for row in rows:
        prepared.append((row, _utc(row.observed_at), _clean_imo(row.imo), _clean_mmsi(row.mmsi)))
    prepared.sort(key=lambda item: item[1])

    conflicts = _recent_mmsi_imo_conflicts(prepared, conflict_window_days=conflict_window_days)
    warnings: set[str] = set()

    official_imos = {imo for row, _, imo, _ in prepared if row.official_registry and imo}
    if len(official_imos) > 1:
        conflicts.add("multiple_official_imo")

    valid_imos = [imo for _, _, imo, _ in prepared if imo]
    canonical_imo: str | None = None
    if len(official_imos) == 1:
        canonical_imo = next(iter(official_imos))
    elif valid_imos:
        # Most frequently observed valid IMO wins; latest observation breaks ties.
        counts = {imo: valid_imos.count(imo) for imo in set(valid_imos)}
        latest = {imo: max(at for _, at, item_imo, _ in prepared if item_imo == imo) for imo in counts}
        canonical_imo = max(counts, key=lambda imo: (counts[imo], latest[imo]))

    mmsis_for_imo: list[tuple[datetime, str]] = []
    if canonical_imo:
        mmsis_for_imo = [(at, mmsi) for _, at, imo, mmsi in prepared if imo == canonical_imo and mmsi]
        if len({mmsi for _, mmsi in mmsis_for_imo}) > 1:
            warnings.add("mmsi_changed_for_imo")

    canonical_mmsi: str | None = None
    if mmsis_for_imo:
        canonical_mmsi = max(mmsis_for_imo, key=lambda item: item[0])[1]
    else:
        valid_mmsis = [(at, mmsi) for _, at, _, mmsi in prepared if mmsi]
        if valid_mmsis:
            canonical_mmsi = max(valid_mmsis, key=lambda item: item[0])[1]

    candidate_names: list[tuple[datetime, str]] = []
    for row, at, imo, mmsi in prepared:
        name = normalize_vessel_name(row.vessel_name)
        if not name:
            continue
        if canonical_imo and imo == canonical_imo:
            candidate_names.append((at, name))
        elif not canonical_imo and canonical_mmsi and mmsi == canonical_mmsi:
            candidate_names.append((at, name))
        elif not canonical_imo and not canonical_mmsi:
            candidate_names.append((at, name))
    canonical_name = max(candidate_names, key=lambda item: item[0])[1] if candidate_names else None

    if conflicts:
        status = "CONFLICT"
        confidence = 0.0
    elif canonical_imo:
        status = "RESOLVED_IMO"
        confidence = 1.0 if canonical_imo in official_imos else 0.98
    elif canonical_mmsi:
        status = "RESOLVED_MMSI"
        confidence = 0.95
    elif canonical_name:
        status = "NAME_ONLY"
        confidence = 0.60
    else:
        status = "UNRESOLVED"
        confidence = 0.0

    return VesselIdentityResolution(
        status=status,
        canonical_imo=canonical_imo,
        canonical_mmsi=canonical_mmsi,
        canonical_name=canonical_name,
        confidence=confidence,
        conflicts=tuple(sorted(conflicts)),
        warnings=tuple(sorted(warnings)),
        source_ids=tuple(sorted({row.source_id for row in rows})),
    )
