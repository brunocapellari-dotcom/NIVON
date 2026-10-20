# Adapted from AgroLogMT/models/shipping_reconciliation.py (main 2026-10-19); review provenance before external release.
from __future__ import annotations

import math
import re
import unicodedata
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from difflib import SequenceMatcher
from typing import Iterable, Sequence


AIS_ZONE_PRIORITY = {
    "UNKNOWN": 0,
    "SEA": 1,
    "APPROACH": 2,
    "ANCHORAGE": 3,
    "BERTH": 4,
    "DEPARTED": 5,
}

SAFE_PORT_ALIASES = {
    "PARANAGUA": frozenset({"PARANAGUA", "PARANAGUA_ANTONINA"}),
}


def _utc(value: datetime | str | None) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        dt = value
    else:
        text = str(value).strip().replace("Z", "+00:00")
        dt = datetime.fromisoformat(text)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def normalize_vessel_name(value: str | None) -> str:
    if not value:
        return ""
    text = unicodedata.normalize("NFKD", value).encode("ascii", "ignore").decode("ascii")
    text = text.upper().strip()
    text = re.sub(r"\b(MV|M/V|MT|M/T|SS|MOTOR VESSEL)\b", " ", text)
    text = re.sub(r"[^A-Z0-9]+", " ", text)
    return " ".join(text.split())


def name_similarity(a: str | None, b: str | None) -> float:
    left, right = normalize_vessel_name(a), normalize_vessel_name(b)
    if not left or not right:
        return 0.0
    if left == right:
        return 1.0
    return SequenceMatcher(None, left, right).ratio()


def _same_port(expected: str | None, observed: str | None) -> bool:
    if not expected or not observed:
        return False
    left = expected.strip().upper()
    right = observed.strip().upper()
    if left == right:
        return True
    aliases = SAFE_PORT_ALIASES.get(left)
    return aliases is not None and right in aliases


@dataclass(frozen=True)
class LineupCall:
    call_id: str
    port_id: str
    vessel_name: str
    eta: datetime | str
    collected_at: datetime | str
    terminal_id: str | None = None
    imo: str | None = None
    mmsi: str | None = None
    product: str | None = None
    planned_volume_t: float | None = None
    lineup_status: str = "PROGRAMMED"
    source_id: str = "lineup"

    @property
    def eta_utc(self) -> datetime:
        value = _utc(self.eta)
        if value is None:
            raise ValueError("eta obrigatorio")
        return value


@dataclass(frozen=True)
class AISObservation:
    observed_at: datetime | str
    mmsi: str | None = None
    imo: str | None = None
    vessel_name: str | None = None
    latitude: float | None = None
    longitude: float | None = None
    sog_kn: float | None = None
    cog_deg: float | None = None
    navigation_status: str | None = None
    destination: str | None = None
    port_id: str | None = None
    terminal_id: str | None = None
    zone: str = "UNKNOWN"
    source_id: str = "ais"

    @property
    def observed_at_utc(self) -> datetime:
        value = _utc(self.observed_at)
        if value is None:
            raise ValueError("observed_at obrigatorio")
        return value


@dataclass(frozen=True)
class PortOperation:
    call_id: str
    port_id: str
    source_id: str
    actual_arrival_at: datetime | str | None = None
    berth_at: datetime | str | None = None
    unberth_at: datetime | str | None = None
    completed_at: datetime | str | None = None
    actual_volume_t: float | None = None
    operation_status: str | None = None


@dataclass(frozen=True)
class VesselMatch:
    call_id: str
    matched: bool
    method: str
    confidence: float
    imo: str | None = None
    mmsi: str | None = None
    vessel_name: str | None = None
    reasons: tuple[str, ...] = ()


@dataclass(frozen=True)
class ReconciledCall:
    call_id: str
    state: str
    evidence_class: str
    match: VesselMatch
    eta_error_hours: float | None = None
    waiting_hours: float | None = None
    berth_hours: float | None = None
    volume_variance_pct: float | None = None
    flags: tuple[str, ...] = ()
    metadata: dict[str, object] = field(default_factory=dict)


def _identity_conflict(call: LineupCall, obs: AISObservation) -> bool:
    if call.imo and obs.imo and str(call.imo) != str(obs.imo):
        return True
    if call.mmsi and obs.mmsi and str(call.mmsi) != str(obs.mmsi):
        return True
    return False


def match_lineup_call(
    call: LineupCall,
    observations: Sequence[AISObservation],
    *,
    time_window_days: int = 21,
    min_name_similarity: float = 0.88,
) -> VesselMatch:
    """Match line-up identity to AIS with deterministic identifiers first.

    Hard rule: if both sources expose an IMO/MMSI and the values conflict, fuzzy-name
    matching is not allowed to override the conflict.
    """
    start = call.eta_utc - timedelta(days=time_window_days)
    end = call.eta_utc + timedelta(days=time_window_days)
    # A matching IMO/MMSI in another known port is not evidence for this call.
    # Unassigned open-sea positions remain eligible until scoped by lifecycle.
    candidates = [
        o for o in observations
        if start <= o.observed_at_utc <= end
        and (o.port_id is None or _same_port(call.port_id, o.port_id))
    ]

    exact_imo = [o for o in candidates if call.imo and o.imo and str(call.imo) == str(o.imo)]
    if exact_imo:
        obs = max(exact_imo, key=lambda x: x.observed_at_utc)
        return VesselMatch(call.call_id, True, "IMO", 1.0, obs.imo, obs.mmsi, obs.vessel_name, ("exact_imo",))

    exact_mmsi = [o for o in candidates if call.mmsi and o.mmsi and str(call.mmsi) == str(o.mmsi)]
    if exact_mmsi:
        obs = max(exact_mmsi, key=lambda x: x.observed_at_utc)
        return VesselMatch(call.call_id, True, "MMSI", 0.99, obs.imo, obs.mmsi, obs.vessel_name, ("exact_mmsi",))

    fuzzy: list[tuple[float, AISObservation, tuple[str, ...]]] = []
    for obs in candidates:
        if _identity_conflict(call, obs):
            continue
        sim = name_similarity(call.vessel_name, obs.vessel_name)
        if sim < min_name_similarity:
            continue
        score = 0.70 + 0.20 * sim
        reasons = [f"name_similarity={sim:.3f}"]
        if obs.port_id and _same_port(call.port_id, obs.port_id):
            score += 0.06
            reasons.append("same_port")
        if call.terminal_id and obs.terminal_id and call.terminal_id == obs.terminal_id:
            score += 0.03
            reasons.append("same_terminal")
        temporal_days = abs((obs.observed_at_utc - call.eta_utc).total_seconds()) / 86400.0
        temporal_bonus = max(0.0, 0.01 * (1.0 - temporal_days / max(time_window_days, 1)))
        score += temporal_bonus
        fuzzy.append((min(score, 0.98), obs, tuple(reasons)))

    if not fuzzy:
        return VesselMatch(call.call_id, False, "NONE", 0.0, reasons=("no_safe_match",))
    score, obs, reasons = max(fuzzy, key=lambda x: x[0])
    return VesselMatch(call.call_id, True, "NAME_FUZZY", score, obs.imo, obs.mmsi, obs.vessel_name, reasons)


def observations_for_match(match: VesselMatch, observations: Iterable[AISObservation]) -> list[AISObservation]:
    if not match.matched:
        return []
    selected: list[AISObservation] = []
    for obs in observations:
        if match.imo and obs.imo and str(match.imo) == str(obs.imo):
            selected.append(obs)
        elif match.mmsi and obs.mmsi and str(match.mmsi) == str(obs.mmsi):
            selected.append(obs)
        elif match.method == "NAME_FUZZY" and name_similarity(match.vessel_name, obs.vessel_name) >= 0.94:
            selected.append(obs)
    return sorted(selected, key=lambda x: x.observed_at_utc)


def observations_for_call(
    call: LineupCall,
    match: VesselMatch,
    observations: Iterable[AISObservation],
    *,
    time_window_days: int = 21,
) -> list[AISObservation]:
    """Scope matched AIS to the current port call before deriving lifecycle metrics.

    Observations assigned to a different known port are excluded. Open-sea observations
    with `port_id=None` remain eligible so arrival/departure transitions can be detected.
    The legacy `PARANAGUA_ANTONINA` alias is accepted for canonical `PARANAGUA`; the
    combined `ARCO_NORTE_CDP` identifier is intentionally never split automatically.
    """
    start = call.eta_utc - timedelta(days=time_window_days)
    end = call.eta_utc + timedelta(days=time_window_days)
    selected = observations_for_match(match, observations)
    return [
        obs
        for obs in selected
        if start <= obs.observed_at_utc <= end
        and (obs.port_id is None or _same_port(call.port_id, obs.port_id))
    ]


def _first_zone(observations: Sequence[AISObservation], zone: str) -> datetime | None:
    times = [o.observed_at_utc for o in observations if o.zone.upper() == zone]
    return min(times) if times else None


def _last_zone(observations: Sequence[AISObservation], zone: str) -> datetime | None:
    times = [o.observed_at_utc for o in observations if o.zone.upper() == zone]
    return max(times) if times else None


def _first_post_berth_exit(observations: Sequence[AISObservation]) -> datetime | None:
    """Return first observed point outside berth after the last BERTH observation.

    This is an AIS/geofence transition bound, not an official unberthing timestamp.
    Only SEA/APPROACH/DEPARTED are accepted as exit evidence; a later ANCHORAGE point
    is intentionally not treated as port departure.
    """
    last_berth = _last_zone(observations, "BERTH")
    if last_berth is None:
        return None
    exits = [
        o.observed_at_utc
        for o in observations
        if o.observed_at_utc > last_berth and o.zone.upper() in {"SEA", "APPROACH", "DEPARTED"}
    ]
    return min(exits) if exits else None


def derive_ais_state(call: LineupCall, observations: Sequence[AISObservation]) -> tuple[str, tuple[str, ...]]:
    if not observations:
        return "PROGRAMMED", ("no_ais_match",)
    latest = max(observations, key=lambda x: x.observed_at_utc)
    zone = latest.zone.upper()
    flags: list[str] = []

    if latest.port_id and not _same_port(call.port_id, latest.port_id):
        flags.append("ais_port_divergence")
    if call.terminal_id and latest.terminal_id and latest.terminal_id != call.terminal_id and zone == "BERTH":
        flags.append("terminal_divergence")

    if zone == "BERTH":
        return "BERTHED", tuple(flags)
    if zone == "ANCHORAGE":
        return "ARRIVED_WAITING", tuple(flags)
    if zone == "DEPARTED":
        return "DEPARTED_PENDING_REALIZED", tuple(flags)

    last_berth = _last_zone(observations, "BERTH")
    if last_berth is not None and latest.observed_at_utc > last_berth and zone in {"SEA", "APPROACH"}:
        flags.append("ais_departure_from_berth_exit_transition")
        return "DEPARTED_PENDING_REALIZED", tuple(flags)

    if zone == "APPROACH":
        return "APPROACHING", tuple(flags)

    speed = latest.sog_kn if latest.sog_kn is not None and math.isfinite(latest.sog_kn) else 0.0
    if zone == "SEA" or speed > 0.5:
        return "IN_TRANSIT", tuple(flags)
    return "AIS_OBSERVED_UNKNOWN_STATE", tuple(flags)


def _hours(later: datetime | None, earlier: datetime | None) -> float | None:
    if later is None or earlier is None:
        return None
    return (later - earlier).total_seconds() / 3600.0


def _volume_variance_pct(planned: float | None, actual: float | None) -> float | None:
    if planned is None or actual is None or planned == 0:
        return None
    return 100.0 * (actual - planned) / planned


def reconcile_call(
    call: LineupCall,
    observations: Sequence[AISObservation],
    operation: PortOperation | None = None,
) -> ReconciledCall:
    if operation is not None:
        if operation.call_id != call.call_id or not _same_port(call.port_id, operation.port_id):
            raise ValueError("official operation does not belong to this port call")
        if not operation.source_id or not operation.source_id.strip():
            raise ValueError("official operation requires source provenance")

    match = match_lineup_call(call, observations)
    vessel_obs = observations_for_call(call, match, observations)
    state, state_flags = derive_ais_state(call, vessel_obs)
    flags = list(state_flags)

    arrival = _first_zone(vessel_obs, "ANCHORAGE") or _first_zone(vessel_obs, "BERTH")
    berth = _first_zone(vessel_obs, "BERTH")
    explicit_departed = _first_zone(vessel_obs, "DEPARTED")
    transition_departed = _first_post_berth_exit(vessel_obs)
    departed = explicit_departed or transition_departed
    departure_detection = "explicit_zone" if explicit_departed else None
    if departed is not None and explicit_departed is None:
        flags.append("ais_departure_from_berth_exit_transition")
        departure_detection = "berth_exit_transition_upper_bound"
    evidence_class = "AIS_OBSERVED" if match.matched else "LINEUP_PROGRAMMED"

    if operation is not None:
        op_arrival = _utc(operation.actual_arrival_at)
        op_berth = _utc(operation.berth_at)
        op_unberth = _utc(operation.unberth_at)
        op_completed = _utc(operation.completed_at)
        arrival = op_arrival or arrival
        berth = op_berth or berth
        if op_unberth is not None:
            departed = op_unberth
            departure_detection = "port_operation_observed"
        status = (operation.operation_status or "").upper()
        if op_completed is not None or status in {"COMPLETED", "REALIZED", "CONCLUDED"}:
            state = "COMPLETED_REALIZED"
            evidence_class = "PORT_OPERATION_OBSERVED"
        elif op_berth is not None or status in {"BERTHED", "OPERATING"}:
            state = "BERTHED"
            evidence_class = "PORT_OPERATION_OBSERVED"
        elif op_arrival is not None or status in {"ARRIVED", "WAITING"}:
            state = "ARRIVED_WAITING"
            evidence_class = "PORT_OPERATION_OBSERVED"

    if call.lineup_status.upper() in {"BERTHED", "ATRACADO"} and state == "ARRIVED_WAITING":
        flags.append("lineup_says_berthed_but_ais_waiting")
    if call.lineup_status.upper() in {"COMPLETED", "REALIZED", "CONCLUDED"} and state != "COMPLETED_REALIZED":
        flags.append("lineup_realized_not_confirmed")

    eta_error = _hours(arrival, call.eta_utc)
    waiting = _hours(berth, arrival)
    berth_hours = _hours(departed, berth)
    volume_var = _volume_variance_pct(call.planned_volume_t, operation.actual_volume_t if operation else None)

    return ReconciledCall(
        call_id=call.call_id,
        state=state,
        evidence_class=evidence_class,
        match=match,
        eta_error_hours=eta_error,
        waiting_hours=waiting,
        berth_hours=berth_hours,
        volume_variance_pct=volume_var,
        flags=tuple(sorted(set(flags))),
        metadata={
            "planned_eta": call.eta_utc.isoformat(),
            "arrival_at": arrival.isoformat() if arrival else None,
            "berth_at": berth.isoformat() if berth else None,
            "departure_at": departed.isoformat() if departed else None,
            "departure_detection": departure_detection,
            "ais_observations_scoped": len(vessel_obs),
            "planned_volume_t": call.planned_volume_t,
            "actual_volume_t": operation.actual_volume_t if operation else None,
        },
    )


def lineup_reliability_score(reconciled: Sequence[ReconciledCall]) -> dict[str, float | int]:
    """Descriptive score, not a predictive model.

    Score rewards realized calls, ETA accuracy and volume accuracy where observed.
    Missing actual volume does not count as zero; the weight is redistributed.
    """
    if not reconciled:
        return {"score": 0.0, "calls": 0, "realized_share": 0.0, "matched_share": 0.0}

    realized = [r for r in reconciled if r.state == "COMPLETED_REALIZED"]
    matched = [r for r in reconciled if r.match.matched]
    realized_share = len(realized) / len(reconciled)
    matched_share = len(matched) / len(reconciled)

    eta_scores = []
    volume_scores = []
    for row in realized:
        if row.eta_error_hours is not None:
            eta_scores.append(max(0.0, 1.0 - abs(row.eta_error_hours) / 72.0))
        if row.volume_variance_pct is not None:
            volume_scores.append(max(0.0, 1.0 - abs(row.volume_variance_pct) / 25.0))

    components: list[tuple[float, float]] = [(0.40, realized_share), (0.20, matched_share)]
    if eta_scores:
        components.append((0.25, sum(eta_scores) / len(eta_scores)))
    if volume_scores:
        components.append((0.15, sum(volume_scores) / len(volume_scores)))
    total_weight = sum(w for w, _ in components)
    score = 100.0 * sum(w * v for w, v in components) / total_weight
    return {
        "score": round(score, 2),
        "calls": len(reconciled),
        "realized_share": round(realized_share, 4),
        "matched_share": round(matched_share, 4),
    }
