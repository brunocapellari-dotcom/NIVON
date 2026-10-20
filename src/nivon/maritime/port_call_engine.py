# Adapted from AgroLogMT/models/port_call_engine.py (main 2026-10-19); internal use, validate provenance before release.
from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Iterable

from nivon.maritime.maritime_port_state import MaritimePhysicalState


@dataclass(frozen=True)
class AisStatePoint:
    observed_at: str
    mmsi: str
    port_id: str | None
    zone: str
    quality_status: str
    corroborated: bool
    sog_kn: float | None = None
    terminal_id: str | None = None
    observation_id: str | None = None


@dataclass(frozen=True)
class OfficialPortSignal:
    observed_at: str
    state: str
    source_id: str
    terminal_id: str | None = None
    official_operational: bool = True


@dataclass(frozen=True)
class PortCallEvent:
    state: str
    occurred_at: str
    evidence_class: str
    source_kind: str
    confidence: float
    terminal_id: str | None
    evidence_refs: tuple[str, ...]
    flags: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class PortCallReconstruction:
    status: str
    current_state: str
    events: tuple[PortCallEvent, ...]
    first_seen_at: str | None
    last_seen_at: str | None
    waiting_hours: float | None
    berth_hours: float | None
    flags: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _utc(value: str) -> datetime:
    parsed = datetime.fromisoformat(str(value).strip().replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError("timestamp de port call deve ter timezone")
    return parsed.astimezone(timezone.utc)


def _state_token(value: str) -> str:
    return str(value).strip().upper().replace(" ", "_").replace("Á", "A").replace("Ç", "C").replace("Ã", "A")


def _append_event(events: list[PortCallEvent], event: PortCallEvent) -> None:
    target = MaritimePhysicalState[event.state]
    if events:
        prior = MaritimePhysicalState[events[-1].state]
        if target < prior:
            return
        if target == prior:
            return
    events.append(event)


def _zone_run(points: list[AisStatePoint], zone: str, *, after: datetime | None = None) -> list[AisStatePoint]:
    target = zone.upper()
    selected = [
        point for point in points
        if point.zone.upper() == target and (after is None or _utc(point.observed_at) > after)
    ]
    return selected


def _corroborated_run(
    points: list[AisStatePoint],
    zone: str,
    *,
    minimum_messages: int,
    minimum_dwell_minutes: float,
    after: datetime | None = None,
) -> list[AisStatePoint]:
    # A dwell event must be supported by one uninterrupted, bounded-gap sequence.
    # Filtering by zone first would incorrectly join positions across a voyage,
    # a berth exit, or a multi-hour AIS coverage outage.
    ordered = sorted(points, key=lambda point: _utc(point.observed_at))
    run: list[AisStatePoint] = []
    max_gap_minutes = 60.0

    def supported(candidate: list[AisStatePoint]) -> bool:
        return (
            len(candidate) >= minimum_messages
            and (_utc(candidate[-1].observed_at) - _utc(candidate[0].observed_at)).total_seconds() / 60.0
            >= minimum_dwell_minutes
        )

    for point in ordered:
        observed = _utc(point.observed_at)
        eligible = (
            (after is None or observed > after)
            and point.zone.upper() == zone.upper()
            and point.corroborated
            and point.quality_status == "CONFIRMED_SEQUENCE"
        )
        if not eligible:
            if supported(run):
                return run
            run = []
            continue
        if run and (observed - _utc(run[-1].observed_at)).total_seconds() / 60.0 > max_gap_minutes:
            if supported(run):
                return run
            run = []
        run.append(point)

    return run if supported(run) else []


def reconstruct_port_call(
    *,
    port_id: str,
    ais_points: Iterable[AisStatePoint],
    official_signals: Iterable[OfficialPortSignal] = (),
    scheduled_at: str | None = None,
    anchorage_dwell_minutes: float = 10.0,
    waiting_dwell_minutes: float = 30.0,
    berth_dwell_minutes: float = 5.0,
) -> PortCallReconstruction:
    """Reconstruct one physical port call using corroborated AIS plus official signals.

    AIS may establish movement/location states only after a coherent sequence. OPERANDO
    and CONCLUIDO are accepted solely from explicit official operational evidence.
    Quarantined or single AIS positions remain auditable input but cannot change state.
    """
    canonical_port = port_id.strip().upper()
    if not canonical_port:
        raise ValueError("port_id obrigatório")

    points = sorted(list(ais_points), key=lambda point: _utc(point.observed_at))
    official = sorted(list(official_signals), key=lambda signal: _utc(signal.observed_at))
    flags: set[str] = set()
    events: list[PortCallEvent] = []

    relevant_points: list[AisStatePoint] = []
    for point in points:
        if point.quality_status == "QUARANTINE":
            flags.add("quarantined_ais_excluded")
            continue
        if point.port_id not in {None, canonical_port}:
            flags.add("other_port_ais_excluded")
            continue
        relevant_points.append(point)

    if scheduled_at:
        _append_event(events, PortCallEvent(
            state="PROGRAMADO",
            occurred_at=_utc(scheduled_at).isoformat(),
            evidence_class="INFORMADO",
            source_kind="LINEUP",
            confidence=1.0,
            terminal_id=None,
            evidence_refs=("scheduled_at",),
        ))

    position_points = [
        point for point in relevant_points
        if point.corroborated and point.quality_status == "CONFIRMED_SEQUENCE"
    ]
    if position_points:
        sea = [point for point in position_points if point.zone.upper() == "SEA"]
        if sea:
            first = sea[0]
            _append_event(events, PortCallEvent(
                state="EM_VIAGEM",
                occurred_at=_utc(first.observed_at).isoformat(),
                evidence_class="OBSERVADO",
                source_kind="AIS",
                confidence=0.80,
                terminal_id=first.terminal_id,
                evidence_refs=tuple(filter(None, (first.observation_id,))),
            ))

        approach = _corroborated_run(position_points, "APPROACH", minimum_messages=2, minimum_dwell_minutes=1.0)
        if approach:
            _append_event(events, PortCallEvent(
                state="APROXIMACAO",
                occurred_at=_utc(approach[0].observed_at).isoformat(),
                evidence_class="OBSERVADO",
                source_kind="AIS_GEOFENCE",
                confidence=0.86,
                terminal_id=approach[0].terminal_id,
                evidence_refs=tuple(filter(None, (point.observation_id for point in approach[:3]))),
            ))

        port_area = _corroborated_run(position_points, "PORT", minimum_messages=2, minimum_dwell_minutes=1.0)
        if port_area:
            _append_event(events, PortCallEvent(
                state="AREA_PORTUARIA",
                occurred_at=_utc(port_area[0].observed_at).isoformat(),
                evidence_class="OBSERVADO",
                source_kind="AIS_GEOFENCE",
                confidence=0.88,
                terminal_id=port_area[0].terminal_id,
                evidence_refs=tuple(filter(None, (point.observation_id for point in port_area[:3]))),
            ))

        anchorage = _corroborated_run(
            position_points,
            "ANCHORAGE",
            minimum_messages=2,
            minimum_dwell_minutes=anchorage_dwell_minutes,
        )
        if anchorage:
            _append_event(events, PortCallEvent(
                state="FUNDEADO",
                occurred_at=_utc(anchorage[0].observed_at).isoformat(),
                evidence_class="INFERIDO",
                source_kind="AIS_GEOFENCE_DWELL",
                confidence=0.88,
                terminal_id=anchorage[0].terminal_id,
                evidence_refs=tuple(filter(None, (point.observation_id for point in anchorage[:4]))),
                flags=("anchorage_dwell_inference",),
            ))
            dwell = (_utc(anchorage[-1].observed_at) - _utc(anchorage[0].observed_at)).total_seconds() / 60.0
            if dwell >= waiting_dwell_minutes:
                waiting_at = _utc(anchorage[0].observed_at) + timedelta(minutes=waiting_dwell_minutes)
                _append_event(events, PortCallEvent(
                    state="AGUARDANDO",
                    occurred_at=waiting_at.isoformat(),
                    evidence_class="INFERIDO",
                    source_kind="AIS_GEOFENCE_DWELL",
                    confidence=0.85,
                    terminal_id=anchorage[-1].terminal_id,
                    evidence_refs=tuple(filter(None, (point.observation_id for point in anchorage[-4:]))),
                    flags=("waiting_threshold_reached",),
                ))

        channel = _corroborated_run(position_points, "CHANNEL", minimum_messages=2, minimum_dwell_minutes=0.5)
        if channel:
            _append_event(events, PortCallEvent(
                state="MANOBRA",
                occurred_at=_utc(channel[0].observed_at).isoformat(),
                evidence_class="INFERIDO",
                source_kind="AIS_GEOFENCE",
                confidence=0.82,
                terminal_id=channel[0].terminal_id,
                evidence_refs=tuple(filter(None, (point.observation_id for point in channel[:3]))),
                flags=("channel_state_inference",),
            ))

        berth = _corroborated_run(
            position_points,
            "BERTH",
            minimum_messages=2,
            minimum_dwell_minutes=berth_dwell_minutes,
        )
        berth_start = None
        if berth:
            berth_start = _utc(berth[0].observed_at)
            _append_event(events, PortCallEvent(
                state="ATRACADO",
                occurred_at=berth_start.isoformat(),
                evidence_class="INFERIDO",
                source_kind="AIS_GEOFENCE_DWELL",
                confidence=0.90,
                terminal_id=berth[0].terminal_id,
                evidence_refs=tuple(filter(None, (point.observation_id for point in berth[:4]))),
                flags=("berth_presence_not_operation_completion",),
            ))
    else:
        berth_start = None

    for signal in official:
        if not signal.official_operational:
            flags.add("nonofficial_port_signal_excluded")
            continue
        token = _state_token(signal.state)
        aliases = {
            "BERTHED": "ATRACADO",
            "ATRACADO": "ATRACADO",
            "OPERATING": "OPERANDO",
            "OPERANDO": "OPERANDO",
            "COMPLETED": "CONCLUIDO",
            "CONCLUDED": "CONCLUIDO",
            "CONCLUIDO": "CONCLUIDO",
            "UNBERTHED": "DESATRACADO",
            "DESATRACADO": "DESATRACADO",
            "DEPARTED": "SAIU",
            "SAIU": "SAIU",
        }
        target = aliases.get(token)
        if target is None:
            flags.add(f"unknown_official_state:{token}")
            continue
        _append_event(events, PortCallEvent(
            state=target,
            occurred_at=_utc(signal.observed_at).isoformat(),
            evidence_class="OBSERVADO",
            source_kind="PORT_OPERATION_OFFICIAL",
            confidence=1.0,
            terminal_id=signal.terminal_id,
            evidence_refs=(signal.source_id,),
        ))

    # AIS after a prior berth can support physical unberthing/departure but never
    # replaces official completion/realized tonnage.
    if berth_start is not None:
        post_berth = [point for point in position_points if _utc(point.observed_at) > berth_start]
        departure_channel = _corroborated_run(
            post_berth, "CHANNEL", minimum_messages=2, minimum_dwell_minutes=0.5, after=berth_start
        )
        if departure_channel:
            _append_event(events, PortCallEvent(
                state="DESATRACADO",
                occurred_at=_utc(departure_channel[0].observed_at).isoformat(),
                evidence_class="INFERIDO",
                source_kind="AIS_BERTH_EXIT",
                confidence=0.80,
                terminal_id=departure_channel[0].terminal_id,
                evidence_refs=tuple(filter(None, (point.observation_id for point in departure_channel[:3]))),
                flags=("physical_unberthing_inferred_not_official_completion",),
            ))
        departure_sea = _corroborated_run(
            post_berth, "SEA", minimum_messages=2, minimum_dwell_minutes=1.0, after=berth_start
        )
        if departure_sea:
            _append_event(events, PortCallEvent(
                state="SAIU",
                occurred_at=_utc(departure_sea[0].observed_at).isoformat(),
                evidence_class="INFERIDO",
                source_kind="AIS_PORT_EXIT",
                confidence=0.82,
                terminal_id=None,
                evidence_refs=tuple(filter(None, (point.observation_id for point in departure_sea[:3]))),
                flags=("physical_port_exit_inferred",),
            ))

    events.sort(key=lambda event: _utc(event.occurred_at))
    # Re-apply monotonic lifecycle after combining sources ordered by time.
    monotonic: list[PortCallEvent] = []
    for event in events:
        if not monotonic or MaritimePhysicalState[event.state] > MaritimePhysicalState[monotonic[-1].state]:
            monotonic.append(event)
        elif MaritimePhysicalState[event.state] == MaritimePhysicalState[monotonic[-1].state]:
            continue
        else:
            flags.add("out_of_order_state_evidence")

    waiting_start = next((_utc(event.occurred_at) for event in monotonic if event.state in {"FUNDEADO", "AGUARDANDO"}), None)
    berth_event = next((_utc(event.occurred_at) for event in monotonic if event.state == "ATRACADO"), None)
    unberth_event = next((_utc(event.occurred_at) for event in monotonic if event.state == "DESATRACADO"), None)
    waiting_hours = None
    berth_hours = None
    if waiting_start is not None and berth_event is not None and berth_event >= waiting_start:
        waiting_hours = (berth_event - waiting_start).total_seconds() / 3600.0
    if berth_event is not None and unberth_event is not None and unberth_event >= berth_event:
        berth_hours = (unberth_event - berth_event).total_seconds() / 3600.0

    first_seen = _utc(relevant_points[0].observed_at).isoformat() if relevant_points else None
    last_seen = _utc(relevant_points[-1].observed_at).isoformat() if relevant_points else None
    current_state = monotonic[-1].state if monotonic else "PROGRAMADO"
    status = "RECONSTRUCTED" if monotonic else "DATA_GATED"
    return PortCallReconstruction(
        status=status,
        current_state=current_state,
        events=tuple(monotonic),
        first_seen_at=first_seen,
        last_seen_at=last_seen,
        waiting_hours=waiting_hours,
        berth_hours=berth_hours,
        flags=tuple(sorted(flags)),
    )
