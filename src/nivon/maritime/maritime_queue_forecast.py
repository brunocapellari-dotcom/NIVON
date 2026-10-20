# Adapted from AgroLogMT/models/maritime_queue_forecast.py (main 2026-10-19); internal use, validate provenance before release.
from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any, Iterable


@dataclass(frozen=True)
class QueueForecastPoint:
    horizon_hours: int
    waiting_expected: float | None
    waiting_low: float | None
    waiting_high: float | None
    status: str
    confidence: float

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class QueueForecastResult:
    status: str
    publication_mode: str
    model_version: str
    service_rate_per_hour: float | None
    points: tuple[QueueForecastPoint, ...]
    flags: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            **asdict(self),
            "points": [point.to_dict() for point in self.points],
        }


def forecast_queue(
    *,
    current_waiting: int,
    arrivals_by_horizon: dict[int, float],
    historical_service_rates_per_hour: Iterable[float],
    horizons: tuple[int, ...] = (6, 24, 48),
    minimum_service_samples: int = 30,
    geofences_validated: bool = False,
    source_fresh: bool = False,
) -> QueueForecastResult:
    """Queue nowcast baseline using explicit arrivals and observed berth service rate.

    This is a conservative mass-balance baseline, not a claim about individual berth
    assignment. It remains SHADOW until enough observed service-rate history exists.
    """
    if current_waiting < 0:
        raise ValueError("current_waiting não pode ser negativo")
    if any(int(horizon) <= 0 for horizon in horizons):
        raise ValueError("horizons devem ser positivos")
    if any(float(value) < 0 for value in arrivals_by_horizon.values()):
        raise ValueError("arrivals_by_horizon não pode ser negativo")

    rates = [float(rate) for rate in historical_service_rates_per_hour if float(rate) >= 0]
    flags: list[str] = []
    if not geofences_validated:
        flags.append("geofences_not_validated")
    if not source_fresh:
        flags.append("source_not_fresh")
    if len(rates) < max(1, int(minimum_service_samples)):
        flags.append("insufficient_service_history")

    service_rate = sum(rates) / len(rates) if rates else None
    if flags or service_rate is None:
        return QueueForecastResult(
            status="DATA_GATED",
            publication_mode="SHADOW",
            model_version="QUEUE_MASS_BALANCE_V1",
            service_rate_per_hour=service_rate,
            points=tuple(
                QueueForecastPoint(int(h), None, None, None, "DATA_GATED", 0.0)
                for h in sorted(set(horizons))
            ),
            flags=tuple(sorted(flags)),
        )

    mean = service_rate
    variance = sum((rate - mean) ** 2 for rate in rates) / max(1, len(rates) - 1)
    std = variance ** 0.5
    low_service = max(0.0, mean - 1.28 * std)
    high_service = max(mean, mean + 1.28 * std)

    points: list[QueueForecastPoint] = []
    for horizon in sorted(set(int(h) for h in horizons)):
        arrivals = float(arrivals_by_horizon.get(horizon, 0.0))
        expected = max(0.0, current_waiting + arrivals - mean * horizon)
        # A slower service rate gives the high queue bound. A faster rate gives low.
        low = max(0.0, current_waiting + arrivals - high_service * horizon)
        high = max(0.0, current_waiting + arrivals - low_service * horizon)
        confidence = max(0.35, 0.80 - 0.005 * horizon)
        points.append(QueueForecastPoint(
            horizon_hours=horizon,
            waiting_expected=expected,
            waiting_low=low,
            waiting_high=high,
            status="SHADOW_ESTIMATE",
            confidence=confidence,
        ))

    return QueueForecastResult(
        status="SHADOW_READY",
        publication_mode="SHADOW",
        model_version="QUEUE_MASS_BALANCE_V1",
        service_rate_per_hour=service_rate,
        points=tuple(points),
        flags=tuple(sorted(flags)),
    )
