# Adapted from AgroLogMT/models/ais_quality.py (main 2026-10-19); internal use, validate provenance before release.
from __future__ import annotations

import math
import re
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta, timezone
from typing import Any


_MMSI_RE = re.compile(r"^[0-9]{9}$")
_IMO_RE = re.compile(r"^[0-9]{7}$")
_POSITION_MESSAGE_TYPES = {
    "POSITIONREPORT",
    "STANDARDCLASSBCSPositionReport".upper(),
    "EXTENDEDCLASSBEQUIPMENTPOSITIONREPORT",
}


@dataclass(frozen=True)
class AisQualityAssessment:
    quality_status: str
    corroborated: bool
    spoofing_suspected: bool
    flags: tuple[str, ...]
    calculated_speed_kn: float | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def normalize_imo(value: Any) -> str | None:
    if value in (None, ""):
        return None
    text = str(value).strip().upper().removeprefix("IMO").strip()
    return text or None


def valid_mmsi(value: Any) -> bool:
    text = str(value or "").strip()
    return bool(_MMSI_RE.fullmatch(text)) and text != "000000000"


def valid_imo(value: Any) -> bool:
    text = normalize_imo(value)
    if text is None:
        return True
    if not _IMO_RE.fullmatch(text):
        return False
    digits = [int(char) for char in text]
    checksum = sum(digit * weight for digit, weight in zip(digits[:6], range(7, 1, -1))) % 10
    return checksum == digits[-1]


def _parse_timestamp(value: Any) -> datetime | None:
    if value in (None, ""):
        return None
    text = str(value).strip().replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return None
    return parsed.astimezone(timezone.utc)


def valid_position(latitude: Any, longitude: Any) -> bool:
    try:
        lat = float(latitude)
        lon = float(longitude)
    except (TypeError, ValueError):
        return False
    return math.isfinite(lat) and math.isfinite(lon) and -90.0 <= lat <= 90.0 and -180.0 <= lon <= 180.0


def _requires_position(current: dict[str, Any]) -> bool:
    message_type = str(current.get("message_type") or "").strip().upper().replace("_", "")
    if message_type in _POSITION_MESSAGE_TYPES:
        return True
    # AISStream's canonical position payload uses PositionReport. Unknown message
    # types are not trusted as positional merely because coordinates are present.
    return message_type.endswith("POSITIONREPORT")


def _haversine_nm(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    radius_nm = 3440.065
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlambda / 2) ** 2
    return 2 * radius_nm * math.asin(min(1.0, math.sqrt(a)))


def implied_speed_kn(previous: dict[str, Any], current: dict[str, Any]) -> float | None:
    if not valid_position(previous.get("latitude"), previous.get("longitude")):
        return None
    if not valid_position(current.get("latitude"), current.get("longitude")):
        return None
    before = _parse_timestamp(previous.get("observed_at"))
    after = _parse_timestamp(current.get("observed_at"))
    if before is None or after is None or after <= before:
        return None
    hours = (after - before).total_seconds() / 3600.0
    if hours <= 0:
        return None
    distance_nm = _haversine_nm(
        float(previous["latitude"]),
        float(previous["longitude"]),
        float(current["latitude"]),
        float(current["longitude"]),
    )
    return distance_nm / hours


def assess_ais_record(
    current: dict[str, Any],
    *,
    previous: dict[str, Any] | None = None,
    same_identity_message_count: int = 1,
    now: datetime | None = None,
    future_skew_seconds: int = 300,
    impossible_speed_kn: float = 60.0,
    position_jump_nm: float = 25.0,
) -> AisQualityAssessment:
    flags: list[str] = []
    now_utc = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    positional = _requires_position(current)

    if not valid_mmsi(current.get("mmsi")):
        flags.append("invalid_mmsi")
    if not valid_imo(current.get("imo")):
        flags.append("invalid_imo")
    if positional and not valid_position(current.get("latitude"), current.get("longitude")):
        flags.append("invalid_position")

    observed_at = _parse_timestamp(current.get("observed_at"))
    if observed_at is None:
        flags.append("invalid_timestamp")
    elif observed_at > now_utc + timedelta(seconds=future_skew_seconds):
        flags.append("clock_anomaly_future")

    source_timestamp_raw = current.get("source_timestamp_raw")
    if source_timestamp_raw not in (None, "") and _parse_timestamp(source_timestamp_raw) is None:
        flags.append("invalid_source_timestamp")
    if str(current.get("timestamp_basis") or "").upper() == "RECEIVED":
        flags.append("timestamp_received_fallback")

    reported_sog = current.get("sog_kn")
    if reported_sog not in (None, ""):
        try:
            reported_speed = float(reported_sog)
        except (TypeError, ValueError):
            flags.append("invalid_reported_speed")
        else:
            if not math.isfinite(reported_speed) or reported_speed < 0:
                flags.append("invalid_reported_speed")
            elif reported_speed > impossible_speed_kn:
                flags.append("reported_impossible_speed")

    reported_cog = current.get("cog_deg")
    if reported_cog not in (None, ""):
        try:
            course = float(reported_cog)
        except (TypeError, ValueError):
            flags.append("invalid_course")
        else:
            if not math.isfinite(course) or course < 0 or course > 360:
                flags.append("invalid_course")

    calculated_speed = None
    if previous is not None:
        previous_at = _parse_timestamp(previous.get("observed_at"))
        if previous_at is not None and observed_at is not None and observed_at <= previous_at:
            flags.append("clock_anomaly_non_monotonic")

        if str(previous.get("mmsi") or "") == str(current.get("mmsi") or ""):
            previous_imo = normalize_imo(previous.get("imo"))
            current_imo = normalize_imo(current.get("imo"))
            if previous_imo and current_imo and previous_imo != current_imo:
                flags.append("identity_conflict_mmsi_to_imo")

        if positional:
            calculated_speed = implied_speed_kn(previous, current)
            if calculated_speed is not None and calculated_speed > impossible_speed_kn:
                flags.append("impossible_speed")

            if valid_position(previous.get("latitude"), previous.get("longitude")) and valid_position(
                current.get("latitude"), current.get("longitude")
            ):
                before = _parse_timestamp(previous.get("observed_at"))
                after = _parse_timestamp(current.get("observed_at"))
                if before is not None and after is not None and after > before:
                    distance_nm = _haversine_nm(
                        float(previous["latitude"]),
                        float(previous["longitude"]),
                        float(current["latitude"]),
                        float(current["longitude"]),
                    )
                    if distance_nm >= position_jump_nm and (after - before) <= timedelta(minutes=15):
                        flags.append("teleport")

    blocking = {
        "invalid_mmsi",
        "invalid_imo",
        "invalid_position",
        "invalid_timestamp",
        "invalid_source_timestamp",
        "invalid_reported_speed",
        "reported_impossible_speed",
        "invalid_course",
        "clock_anomaly_future",
        "clock_anomaly_non_monotonic",
        "impossible_speed",
        "teleport",
        "identity_conflict_mmsi_to_imo",
    }
    has_blocking = any(flag in blocking for flag in flags)
    corroborated = same_identity_message_count >= 2 and not has_blocking

    anomaly_flags = {
        "teleport",
        "impossible_speed",
        "reported_impossible_speed",
        "clock_anomaly_future",
        "clock_anomaly_non_monotonic",
        "identity_conflict_mmsi_to_imo",
    }
    anomaly_count = sum(flag in anomaly_flags for flag in flags)
    spoofing_suspected = anomaly_count >= 2 and same_identity_message_count >= 2

    if has_blocking:
        status = "QUARANTINE"
    elif not corroborated:
        status = "UNCONFIRMED_SINGLE"
    else:
        status = "CONFIRMED_SEQUENCE"

    return AisQualityAssessment(
        quality_status=status,
        corroborated=corroborated,
        spoofing_suspected=spoofing_suspected,
        flags=tuple(sorted(set(flags))),
        calculated_speed_kn=calculated_speed,
    )
