# Adapted from AgroLogMT/models/maritime_weather.py (main 2026-10-19); review provenance before external release.
from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any


@dataclass(frozen=True)
class MaritimeWeatherRecord:
    source_id: str
    valid_at: str
    evidence_class: str
    wind_kn: float | None = None
    gust_kn: float | None = None
    wave_height_m: float | None = None
    visibility_km: float | None = None
    precipitation_mm_h: float | None = None
    current_kn: float | None = None


@dataclass(frozen=True)
class PortWeatherThresholds:
    source_id: str
    max_wind_kn: float | None = None
    max_gust_kn: float | None = None
    max_wave_height_m: float | None = None
    min_visibility_km: float | None = None
    max_current_kn: float | None = None
    authorized_operational_rule: bool = False


@dataclass(frozen=True)
class WeatherImpactAssessment:
    status: str
    evidence_class: str
    restrictions_claimed: bool
    exceeded: tuple[str, ...]
    flags: tuple[str, ...]
    confidence: float

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def assess_maritime_weather(
    record: MaritimeWeatherRecord,
    *,
    thresholds: PortWeatherThresholds | None = None,
) -> WeatherImpactAssessment:
    """Assess weather exposure without inventing port operating limits.

    Meteorological observations/forecasts alone may describe exposure. An operational
    restriction is asserted only when thresholds come from an authorized port/terminal
    operating rule explicitly marked ``authorized_operational_rule=True``.
    """
    flags: list[str] = []
    exceeded: list[str] = []
    evidence = str(record.evidence_class).strip().upper()
    if evidence not in {"OBSERVADO", "PROJETADO", "ESTIMADO"}:
        raise ValueError("evidence_class meteorológica inválida")

    numeric = {
        "wind_kn": record.wind_kn,
        "gust_kn": record.gust_kn,
        "wave_height_m": record.wave_height_m,
        "visibility_km": record.visibility_km,
        "precipitation_mm_h": record.precipitation_mm_h,
        "current_kn": record.current_kn,
    }
    for name, value in numeric.items():
        if value is not None and float(value) < 0:
            raise ValueError(f"{name} não pode ser negativo")

    if thresholds is None:
        return WeatherImpactAssessment(
            status="EXPOSURE_ONLY",
            evidence_class=evidence,
            restrictions_claimed=False,
            exceeded=(),
            flags=("operational_thresholds_missing",),
            confidence=0.90 if evidence == "OBSERVADO" else 0.70,
        )

    comparisons = (
        ("wind_kn", record.wind_kn, thresholds.max_wind_kn, "max"),
        ("gust_kn", record.gust_kn, thresholds.max_gust_kn, "max"),
        ("wave_height_m", record.wave_height_m, thresholds.max_wave_height_m, "max"),
        ("visibility_km", record.visibility_km, thresholds.min_visibility_km, "min"),
        ("current_kn", record.current_kn, thresholds.max_current_kn, "max"),
    )
    for name, value, threshold, direction in comparisons:
        if value is None or threshold is None:
            continue
        if float(threshold) < 0:
            raise ValueError(f"limiar {name} inválido")
        if direction == "max" and float(value) > float(threshold):
            exceeded.append(name)
        elif direction == "min" and float(value) < float(threshold):
            exceeded.append(name)

    if not thresholds.authorized_operational_rule:
        flags.append("thresholds_not_authorized_for_operational_claim")
        return WeatherImpactAssessment(
            status="THRESHOLD_COMPARISON_ONLY",
            evidence_class="INFERIDO",
            restrictions_claimed=False,
            exceeded=tuple(sorted(exceeded)),
            flags=tuple(flags),
            confidence=0.75,
        )

    if exceeded:
        status = "AUTHORIZED_LIMIT_EXCEEDED"
        flags.append("port_rule_threshold_exceeded")
    else:
        status = "WITHIN_AUTHORIZED_LIMITS"
    return WeatherImpactAssessment(
        status=status,
        evidence_class="INFERIDO",
        restrictions_claimed=bool(exceeded),
        exceeded=tuple(sorted(exceeded)),
        flags=tuple(flags),
        confidence=0.95 if evidence == "OBSERVADO" else 0.80,
    )
