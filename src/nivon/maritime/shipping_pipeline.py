# Adapted from AgroLogMT/models/shipping_pipeline.py (main 2026-10-19); review provenance before external release.
from __future__ import annotations

import hashlib
from dataclasses import asdict
from typing import Iterable, Sequence

from nivon.maritime.shipping_reconciliation import (
    AISObservation,
    LineupCall,
    PortOperation,
    ReconciledCall,
    lineup_reliability_score,
    reconcile_call,
)


def reconcile_lineup_snapshot(
    lineup_calls: Sequence[LineupCall],
    ais_observations: Sequence[AISObservation],
    operations: Iterable[PortOperation] = (),
) -> list[ReconciledCall]:
    operation_by_call = {row.call_id: row for row in operations}
    return [
        reconcile_call(call, ais_observations, operation_by_call.get(call.call_id))
        for call in lineup_calls
    ]


def reconciliation_to_row(row: ReconciledCall) -> dict[str, object]:
    rid = hashlib.sha256(
        f"{row.call_id}|{row.state}|{row.match.method}|{row.metadata.get('arrival_at')}|{row.metadata.get('departure_at')}".encode("utf-8")
    ).hexdigest()
    return {
        "reconciliation_id": rid,
        "call_id": row.call_id,
        "state": row.state,
        "evidence_class": row.evidence_class,
        "match_method": row.match.method,
        "match_confidence": row.match.confidence,
        "matched_imo": row.match.imo,
        "matched_mmsi": row.match.mmsi,
        "eta_error_hours": row.eta_error_hours,
        "waiting_hours": row.waiting_hours,
        "berth_hours": row.berth_hours,
        "volume_variance_pct": row.volume_variance_pct,
        "flags": list(row.flags),
        "metadata": row.metadata,
    }


def reconciliation_alerts(rows: Sequence[ReconciledCall], *, eta_delay_hours: float = 24.0, waiting_hours: float = 24.0) -> list[dict[str, object]]:
    alerts: list[dict[str, object]] = []
    for row in rows:
        if not row.match.matched:
            alerts.append({"call_id": row.call_id, "severity": "ATTENTION", "type": "AIS_UNMATCHED", "detail": "Line-up sem match AIS seguro"})
        if row.eta_error_hours is not None and row.eta_error_hours > eta_delay_hours:
            alerts.append({"call_id": row.call_id, "severity": "ELEVATED", "type": "ETA_DELAY", "value": row.eta_error_hours})
        if row.waiting_hours is not None and row.waiting_hours > waiting_hours:
            alerts.append({"call_id": row.call_id, "severity": "ELEVATED", "type": "ANCHORAGE_WAIT", "value": row.waiting_hours})
        for flag in row.flags:
            severity = "HIGH" if flag in {"ais_port_divergence", "lineup_realized_not_confirmed"} else "ELEVATED"
            alerts.append({"call_id": row.call_id, "severity": severity, "type": "DIVERGENCE", "detail": flag})
    return alerts


def snapshot_summary(rows: Sequence[ReconciledCall]) -> dict[str, object]:
    counts: dict[str, int] = {}
    for row in rows:
        counts[row.state] = counts.get(row.state, 0) + 1
    return {
        "calls": len(rows),
        "states": counts,
        "lineup_reliability": lineup_reliability_score(rows),
        "alerts": len(reconciliation_alerts(rows)),
    }
