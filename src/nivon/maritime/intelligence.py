"""NIVON Maritime: orquestracao deterministica, analise SHADOW, sem efeitos externos."""
from __future__ import annotations
import hashlib
import json
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from .ais_quality import assess_ais_record, valid_position
from .port_geofence import PortZone, classify_position
from .port_call_engine import AisStatePoint, reconstruct_port_call
from .shipping_reconciliation import AISObservation, LineupCall, PortOperation
from .shipping_pipeline import reconcile_lineup_snapshot, reconciliation_to_row, snapshot_summary
from .maritime_queue import QueueSnapshot, evaluate_queue_pressure
from .maritime_queue_forecast import forecast_queue
from .maritime_source_health import assess_source_health
from .maritime_anomaly import detect_maritime_anomalies
from .maritime_alerting import decide_alerts, PriorAlert
from .maritime_weather import MaritimeWeatherRecord, PortWeatherThresholds, assess_maritime_weather
from .maritime_trade_flow import PortTradeAggregate, LineupAggregate, build_trade_flow_signals
from .maritime_final_readiness import evaluate_final_readiness
from .cross_domain import CrossDomainSignal, evaluate_cross_domain


def _utc(value: str | datetime, label: str) -> datetime:
    try:
        dt = value if isinstance(value, datetime) else datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (TypeError, ValueError) as exc:
        raise ValueError(label + ": timestamp invalido") from exc
    if dt.tzinfo is None or dt.utcoffset() is None:
        raise ValueError(label + ": timezone obrigatorio")
    return dt.astimezone(timezone.utc)


@dataclass(frozen=True)
class MaritimeAnalysisRequest:
    port_id: str
    now: str | datetime
    ais_records: tuple[dict[str, Any], ...] = ()
    lineup_calls: tuple[LineupCall, ...] = ()
    official_operations: tuple[PortOperation, ...] = ()
    geofences: tuple[PortZone, ...] = ()
    geofences_validated: bool = False
    ais_collection_authorized: bool = False
    lineup_authorized: bool = False
    official_operations_verified: bool = False
    source_id: str = "AIS_NOT_CONFIGURED"
    source_last_success_at: str | None = None
    source_last_record_at: str | None = None
    expected_interval_minutes: float = 30.0
    historical_waiting_counts: tuple[float, ...] = ()
    historical_service_rates_per_hour: tuple[float, ...] = ()
    arrivals_by_horizon: dict[int, float] = field(default_factory=dict)
    lineup_next_72h: int | None = None
    berth_capacity: int | None = None
    observed_trade: tuple[PortTradeAggregate, ...] = ()
    programmed_trade: tuple[LineupAggregate, ...] = ()
    weather: MaritimeWeatherRecord | None = None
    weather_thresholds: PortWeatherThresholds | None = None
    previous_alerts: tuple[PriorAlert, ...] = ()
    cross_domain_signals: tuple[CrossDomainSignal, ...] = ()
    linked_scope_ids: tuple[str, ...] = ()


class MaritimeIntelligenceCoordinator:
    """O LLM pode interpretar a saida, mas nao controla gates ou estados fisicos."""
    MAX_RECORDS = 50000

    def run(self, request: MaritimeAnalysisRequest) -> dict[str, Any]:
        now = _utc(request.now, "now")
        port = request.port_id.strip().upper()
        if not port:
            raise ValueError("port_id obrigatorio")
        if len(request.ais_records) > self.MAX_RECORDS:
            raise ValueError("lote AIS excessivo")
        if request.geofences_validated and (not request.geofences or any(
            not z.source_id or z.port_id.upper() != port for z in request.geofences
        )):
            raise ValueError("geofences validadas exigem fonte e porto corretos")
        for call in request.lineup_calls:
            if call.port_id.upper() != port:
                raise ValueError("line-up em porto diferente")
            _utc(call.eta, "eta")
            _utc(call.collected_at, "coleta")
        for op in request.official_operations:
            if op.port_id.upper() != port:
                raise ValueError("operacao em porto diferente")
            for f in ("actual_arrival_at", "berth_at", "unberth_at", "completed_at"):
                if getattr(op, f) is not None:
                    _utc(getattr(op, f), f)

        health = assess_source_health(
            source_id=request.source_id, now=now,
            expected_interval_minutes=request.expected_interval_minutes,
            last_success_at=request.source_last_success_at,
            last_record_at=request.source_last_record_at,
        )
        fresh_authorized = (
            health.status == "FRESH" and request.geofences_validated
            and request.ais_collection_authorized
        )
        seen: set[str] = set()
        previous: dict[str, dict[str, Any]] = {}
        counts: dict[str, int] = defaultdict(int)
        quality_rows: list[dict[str, Any]] = []
        trusted: list[AISObservation] = []
        port_points: dict[str, list[AisStatePoint]] = defaultdict(list)
        last_zone: dict[str, tuple[datetime, str]] = {}
        flags: set[str] = set()
        spoofing = False
        duplicates = 0

        for row in request.ais_records:
            if not isinstance(row, dict):
                raise ValueError("registro AIS nao e objeto")
            payload = json.dumps(
                {k: v for k, v in row.items() if k != "_raw_message"},
                sort_keys=True, default=str, allow_nan=False,
            )
            identity = hashlib.sha256(payload.encode("utf-8")).hexdigest()
            if identity in seen:
                duplicates += 1
                continue
            seen.add(identity)
            mmsi = str(row.get("mmsi") or "")
            q = assess_ais_record(
                row, previous=previous.get(mmsi),
                same_identity_message_count=counts[mmsi] + 1, now=now,
            )
            flags.update(q.flags)
            spoofing = spoofing or q.spoofing_suspected
            if q.quality_status != "QUARANTINE":
                counts[mmsi] += 1
            previous[mmsi] = row
            geo: dict[str, str | None] = {"port_id": None, "zone": "UNKNOWN", "terminal_id": None}
            if (fresh_authorized and q.quality_status == "CONFIRMED_SEQUENCE"
                    and valid_position(row.get("latitude"), row.get("longitude"))):
                geo = classify_position(
                    float(row["latitude"]), float(row["longitude"]), request.geofences,
                )
            quality_rows.append({
                "observation_id": identity, "mmsi": mmsi,
                "quality": q.to_dict(), "classified_port_id": geo.get("port_id"),
                "zone": geo.get("zone"),
            })
            if not (fresh_authorized and q.quality_status == "CONFIRMED_SEQUENCE"
                    and geo.get("port_id") == port):
                continue
            stamp = _utc(row["observed_at"], "observed_at")
            obs = AISObservation(
                observed_at=stamp, mmsi=mmsi, imo=row.get("imo"),
                vessel_name=row.get("vessel_name"),
                latitude=float(row["latitude"]), longitude=float(row["longitude"]),
                sog_kn=row.get("sog_kn"), cog_deg=row.get("cog_deg"),
                port_id=port, terminal_id=geo.get("terminal_id"),
                zone=str(geo["zone"]), source_id=request.source_id,
            )
            trusted.append(obs)
            port_points[mmsi].append(AisStatePoint(
                observed_at=stamp.isoformat(), mmsi=mmsi, port_id=port,
                zone=obs.zone, quality_status=q.quality_status,
                corroborated=True, sog_kn=obs.sog_kn,
                terminal_id=obs.terminal_id, observation_id=identity,
            ))
            if mmsi not in last_zone or stamp > last_zone[mmsi][0]:
                last_zone[mmsi] = (stamp, obs.zone)

        reconciled = reconcile_lineup_snapshot(
            request.lineup_calls if request.lineup_authorized else (),
            trusted,
            request.official_operations if request.official_operations_verified else (),
        )
        port_calls = {
            mmsi: reconstruct_port_call(port_id=port, ais_points=points).to_dict()
            for mmsi, points in port_points.items()
        }
        queue = forecast = None
        if last_zone and fresh_authorized:
            zones = [zone for _, zone in last_zone.values()]
            waiting = zones.count("ANCHORAGE")
            snapshot = QueueSnapshot(
                waiting_vessels=waiting, approaching_vessels=zones.count("APPROACH"),
                berthed_vessels=zones.count("BERTH"), waiting_hours=tuple(
                    float(c["waiting_hours"]) for c in port_calls.values()
                    if c["waiting_hours"] is not None
                ),
                lineup_next_72h=(
                    request.lineup_next_72h if request.lineup_authorized
                    and request.lineup_next_72h is not None else 0
                ),
            )
            queue = evaluate_queue_pressure(
                snapshot, historical_waiting_counts=request.historical_waiting_counts,
                geofences_validated=request.geofences_validated,
                source_fresh=fresh_authorized, berth_capacity=request.berth_capacity,
            ).to_dict()
            forecast = forecast_queue(
                current_waiting=waiting, arrivals_by_horizon=request.arrivals_by_horizon,
                historical_service_rates_per_hour=request.historical_service_rates_per_hour,
                geofences_validated=request.geofences_validated,
                source_fresh=fresh_authorized,
            ).to_dict()

        weather = (
            assess_maritime_weather(request.weather, thresholds=request.weather_thresholds).to_dict()
            if request.weather is not None else None
        )
        flows = [
            x.to_dict() for x in build_trade_flow_signals(
                request.observed_trade, request.programmed_trade
            )
        ]
        anomalies = detect_maritime_anomalies(
            ais_quality_flags=flags, spoofing_suspected=spoofing,
            source_health_status=health.status,
            queue_zscore=queue["zscore"] if queue else None,
            queue_percentile=queue["historical_percentile"] if queue else None,
            reconciliation_flags=(f for x in reconciled for f in x.flags),
            corroborated_ais=bool(trusted),
        )
        alert_candidates = decide_alerts(
            scope=port, anomalies=anomalies, now=now,
            prior_alerts=request.previous_alerts,
        )
        cross_domain = evaluate_cross_domain(
            now=now, scope_ids=(port, *request.linked_scope_ids),
            signals=request.cross_domain_signals,
            queue_status=queue['status'] if queue else None,
        ) if request.cross_domain_signals else None
        readiness = evaluate_final_readiness(())
        blockers = list(readiness.blocked_gates)
        if not fresh_authorized:
            blockers.append("ais_not_authorized_fresh_and_geofenced")
        if not request.lineup_authorized:
            blockers.append("lineup_not_authorized")
        if not trusted:
            blockers.append("ais_not_corroborated")
        return {
            "engine": "NIVON_MARITIME_INTELLIGENCE_V1",
            "port_id": port, "calculated_at": now.isoformat(),
            "status": "SHADOW_DIAGNOSTIC", "publication_allowed": False,
            "external_actions_allowed": False,
            "evidence": {
                "ais_received": len(request.ais_records),
                "ais_duplicates_rejected": duplicates,
                "ais_trusted_in_port": len(trusted),
                "ais_quality": quality_rows, "source_health": health.to_dict(),
                "lineup_received": len(request.lineup_calls),
                "lineup_analyzed": len(reconciled),
                "official_operations_verified": request.official_operations_verified,
            },
            "port_calls": port_calls,
            "reconciliation": [reconciliation_to_row(x) for x in reconciled],
            "reconciliation_summary": snapshot_summary(reconciled) if reconciled else None,
            "queue": queue, "queue_forecast": forecast, "weather": weather,
            "trade_flow": flows, "cross_domain": cross_domain,
            "anomalies": [a.to_dict() for a in anomalies],
            "alert_candidates_not_dispatched": [a.to_dict() for a in alert_candidates],
            "release": {
                "status": readiness.status, "blocked_gates": blockers,
                "rule": "AIS alone never confirms cargo or completed port operations",
            },
        }
