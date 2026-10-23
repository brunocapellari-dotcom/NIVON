# Adapted from AgroLogMT/models/maritime_queue.py (main 2026-10-19); internal use, validate provenance before release.
from __future__ import annotations

import math
from dataclasses import asdict, dataclass
from typing import Any, Iterable


@dataclass(frozen=True)
class QueueSnapshot:
    waiting_vessels: int
    approaching_vessels: int
    berthed_vessels: int
    waiting_hours: tuple[float, ...]
    lineup_next_72h: int = 0


@dataclass(frozen=True)
class QueuePressureResult:
    status: str
    publication_mode: str
    vqi: float | None
    port_pressure_score: float | None
    p50_wait_hours: float | None
    p90_wait_hours: float | None
    historical_percentile: float | None
    zscore: float | None
    evidence_class: str
    model_version: str
    flags: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _quantile(values: Iterable[float], probability: float) -> float | None:
    clean = sorted(float(value) for value in values if math.isfinite(float(value)) and float(value) >= 0)
    if not clean:
        return None
    p = max(0.0, min(1.0, float(probability)))
    if len(clean) == 1:
        return clean[0]
    position = p * (len(clean) - 1)
    lower = int(math.floor(position))
    upper = int(math.ceil(position))
    if lower == upper:
        return clean[lower]
    weight = position - lower
    return clean[lower] * (1.0 - weight) + clean[upper] * weight


def _historical_rank(value: float, history: list[float]) -> float:
    if not history:
        return 0.0
    less_or_equal = sum(item <= value for item in history)
    return less_or_equal / len(history)


def _zscore(value: float, history: list[float]) -> float | None:
    if len(history) < 2:
        return None
    mean = sum(history) / len(history)
    variance = sum((item - mean) ** 2 for item in history) / (len(history) - 1)
    if variance <= 0:
        return 0.0 if value == mean else None
    return (value - mean) / math.sqrt(variance)


def evaluate_queue_pressure(
    snapshot: QueueSnapshot,
    *,
    historical_waiting_counts: Iterable[float] = (),
    minimum_history_points: int = 30,
    geofences_validated: bool = False,
    source_fresh: bool = False,
    berth_capacity: int | None = None,
) -> QueuePressureResult:
    """Compute VQI/Port Pressure as shadow indicators until data gates are satisfied.

    Scores are intentionally transparent composites. They are never treated as an
    observed port-authority metric. Historical normalization is required before a
    score may leave DATA_GATED status, and publication remains SHADOW in V1.
    """
    flags: list[str] = []
    if snapshot.waiting_vessels < 0 or snapshot.approaching_vessels < 0 or snapshot.berthed_vessels < 0:
        raise ValueError("contagem de navios não pode ser negativa")
    if snapshot.lineup_next_72h < 0:
        raise ValueError("lineup_next_72h não pode ser negativo")

    p50 = _quantile(snapshot.waiting_hours, 0.50)
    p90 = _quantile(snapshot.waiting_hours, 0.90)
    history = [float(item) for item in historical_waiting_counts if math.isfinite(float(item)) and float(item) >= 0]

    if not geofences_validated:
        flags.append("geofences_not_validated")
    if not source_fresh:
        flags.append("source_not_fresh")
    if len(history) < max(1, int(minimum_history_points)):
        flags.append("insufficient_history")

    percentile = _historical_rank(float(snapshot.waiting_vessels), history) if history else None
    zscore = _zscore(float(snapshot.waiting_vessels), history)

    if flags:
        return QueuePressureResult(
            status="DATA_GATED",
            publication_mode="SHADOW",
            vqi=None,
            port_pressure_score=None,
            p50_wait_hours=p50,
            p90_wait_hours=p90,
            historical_percentile=percentile,
            zscore=zscore,
            evidence_class="INFERIDO",
            model_version="VQI_V1_SHADOW",
            flags=tuple(sorted(flags)),
        )

    # Normalize major drivers to a bounded 0..100 scale. Historical rank carries the
    # largest weight so absolute vessel counts are not compared blindly across ports.
    rank_component = 100.0 * (percentile or 0.0)
    approach_component = min(100.0, snapshot.approaching_vessels * 12.5)
    lineup_component = min(100.0, snapshot.lineup_next_72h * 6.0)
    wait_component = min(100.0, (p90 or 0.0) / 72.0 * 100.0)
    vqi = 0.55 * rank_component + 0.20 * wait_component + 0.15 * approach_component + 0.10 * lineup_component

    berth_component = 0.0
    if berth_capacity is not None:
        if berth_capacity <= 0:
            raise ValueError("berth_capacity deve ser > 0")
        berth_component = min(100.0, 100.0 * snapshot.berthed_vessels / berth_capacity)
    else:
        flags.append("berth_capacity_missing")

    pressure = 0.70 * vqi + 0.30 * berth_component if berth_capacity is not None else vqi
    return QueuePressureResult(
        status="SHADOW_READY",
        publication_mode="SHADOW",
        vqi=round(vqi, 4),
        port_pressure_score=round(pressure, 4),
        p50_wait_hours=p50,
        p90_wait_hours=p90,
        historical_percentile=percentile,
        zscore=zscore,
        evidence_class="INFERIDO",
        model_version="VQI_V1_SHADOW",
        flags=tuple(sorted(flags)),
    )
