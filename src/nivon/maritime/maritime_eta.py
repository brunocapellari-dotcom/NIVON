# Adapted from AgroLogMT/models/maritime_eta.py (main 2026-10-19); internal use, validate provenance before release.
from __future__ import annotations

import math
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta, timezone
from typing import Any


@dataclass(frozen=True)
class EtaEstimate:
    status: str
    eta: str | None
    eta_low: str | None
    eta_high: str | None
    travel_hours: float | None
    effective_speed_kn: float | None
    distance_nm: float | None
    distance_method: str | None
    confidence: float
    evidence_class: str = "ESTIMADO"
    model_version: str = "MARITIME_ETA_BASELINE_V1"
    flags: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _utc(value: datetime | str) -> datetime:
    if isinstance(value, datetime):
        parsed = value
    else:
        parsed = datetime.fromisoformat(str(value).strip().replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError("timestamp ETA deve ter timezone")
    return parsed.astimezone(timezone.utc)


def great_circle_distance_nm(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    for value, minimum, maximum, label in (
        (lat1, -90.0, 90.0, "lat1"),
        (lat2, -90.0, 90.0, "lat2"),
        (lon1, -180.0, 180.0, "lon1"),
        (lon2, -180.0, 180.0, "lon2"),
    ):
        if not math.isfinite(float(value)) or not minimum <= float(value) <= maximum:
            raise ValueError(f"{label} invalida")
    radius_nm = 3440.065
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlambda / 2) ** 2
    return 2 * radius_nm * math.asin(min(1.0, math.sqrt(a)))


def estimate_eta(
    *,
    calculated_at: datetime | str,
    distance_nm: float | None,
    distance_method: str | None,
    current_sog_kn: float | None = None,
    reference_speed_kn: float | None = None,
    congestion_delay_hours: float = 0.0,
    weather_delay_hours: float = 0.0,
    speed_uncertainty_pct: float = 0.20,
    delay_uncertainty_hours: float = 1.0,
    ais_corroborated: bool = True,
) -> EtaEstimate:
    """Compute a transparent ETA baseline.

    ``distance_nm`` must come from an explicit route/geodesic calculation supplied by
    the caller. This function never invents a route. Great-circle distance is allowed
    only when labelled ``GEODESIC_LOWER_BOUND`` and receives a confidence penalty.
    """
    flags: list[str] = []
    calculated = _utc(calculated_at)

    if not ais_corroborated:
        return EtaEstimate(
            status="DATA_GATED",
            eta=None,
            eta_low=None,
            eta_high=None,
            travel_hours=None,
            effective_speed_kn=None,
            distance_nm=distance_nm,
            distance_method=distance_method,
            confidence=0.0,
            flags=("ais_not_corroborated",),
        )

    if distance_nm is None or not math.isfinite(float(distance_nm)) or float(distance_nm) < 0:
        return EtaEstimate(
            status="DATA_GATED",
            eta=None,
            eta_low=None,
            eta_high=None,
            travel_hours=None,
            effective_speed_kn=None,
            distance_nm=distance_nm,
            distance_method=distance_method,
            confidence=0.0,
            flags=("route_distance_missing",),
        )

    method = str(distance_method or "").strip().upper()
    if method not in {"ROUTE_ENGINE", "SEAROUTE", "VALIDATED_CORRIDOR", "GEODESIC_LOWER_BOUND"}:
        return EtaEstimate(
            status="DATA_GATED",
            eta=None,
            eta_low=None,
            eta_high=None,
            travel_hours=None,
            effective_speed_kn=None,
            distance_nm=float(distance_nm),
            distance_method=method or None,
            confidence=0.0,
            flags=("distance_method_unapproved",),
        )

    def usable_speed(value: float | None) -> float | None:
        if value is None:
            return None
        number = float(value)
        if not math.isfinite(number) or number <= 0.5 or number > 45.0:
            return None
        return number

    speed = usable_speed(current_sog_kn)
    speed_source = "CURRENT_SOG"
    if speed is None:
        speed = usable_speed(reference_speed_kn)
        speed_source = "REFERENCE_SPEED"
    if speed is None:
        return EtaEstimate(
            status="DATA_GATED",
            eta=None,
            eta_low=None,
            eta_high=None,
            travel_hours=None,
            effective_speed_kn=None,
            distance_nm=float(distance_nm),
            distance_method=method,
            confidence=0.0,
            flags=("usable_speed_missing",),
        )

    congestion = max(0.0, float(congestion_delay_hours))
    weather = max(0.0, float(weather_delay_hours))
    base_travel = float(distance_nm) / speed
    travel_hours = base_travel + congestion + weather
    eta = calculated + timedelta(hours=travel_hours)

    uncertainty_pct = min(max(float(speed_uncertainty_pct), 0.01), 0.80)
    fast_speed = speed * (1.0 + uncertainty_pct)
    slow_speed = max(0.5, speed * (1.0 - uncertainty_pct))
    delay_uncertainty = max(0.0, float(delay_uncertainty_hours))
    low_hours = float(distance_nm) / fast_speed + max(0.0, congestion + weather - delay_uncertainty)
    high_hours = float(distance_nm) / slow_speed + congestion + weather + delay_uncertainty

    confidence = 0.78 if speed_source == "CURRENT_SOG" else 0.65
    if method == "GEODESIC_LOWER_BOUND":
        confidence -= 0.25
        flags.append("geodesic_is_lower_bound_not_navigable_route")
    if congestion > 0:
        flags.append("congestion_delay_applied")
    if weather > 0:
        flags.append("weather_delay_applied")
    flags.append(f"speed_source:{speed_source}")

    return EtaEstimate(
        status="ESTIMATED",
        eta=eta.isoformat(),
        eta_low=(calculated + timedelta(hours=low_hours)).isoformat(),
        eta_high=(calculated + timedelta(hours=high_hours)).isoformat(),
        travel_hours=travel_hours,
        effective_speed_kn=speed,
        distance_nm=float(distance_nm),
        distance_method=method,
        confidence=max(0.0, min(1.0, confidence)),
        flags=tuple(flags),
    )


def eta_deviation_hours(estimated_eta: datetime | str | None, informed_eta: datetime | str | None) -> float | None:
    if estimated_eta is None or informed_eta is None:
        return None
    return (_utc(estimated_eta) - _utc(informed_eta)).total_seconds() / 3600.0
