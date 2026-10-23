# Reused from AgroLogMT/collector/ais_stream.py; verify provenance/license before commercial release.
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any


def build_subscription(api_key: str, bounding_boxes: list[list[list[float]]], mmsi_filter: list[str] | None = None) -> dict[str, Any]:
    if not api_key:
        raise ValueError("AIS API key obrigatoria")
    if not bounding_boxes:
        raise ValueError("ao menos um bounding box obrigatorio")
    payload: dict[str, Any] = {
        "APIKey": api_key,
        "BoundingBoxes": bounding_boxes,
        "FilterMessageTypes": ["PositionReport", "ShipStaticData"],
    }
    if mmsi_filter:
        payload["FiltersShipMMSI"] = [str(x) for x in mmsi_filter]
    return payload


def _first(mapping: dict[str, Any], *names: str) -> Any:
    lower = {str(k).lower(): v for k, v in mapping.items()}
    for name in names:
        if name.lower() in lower:
            return lower[name.lower()]
    return None


def _float(value: Any) -> float | None:
    if value in (None, ""):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _parse_timestamp(value: Any) -> datetime | None:
    if value in (None, ""):
        return None
    text = str(value).strip().replace("Z", "+00:00")
    try:
        dt = datetime.fromisoformat(text)
    except ValueError:
        return None
    if dt.tzinfo is None:
        # AISStream documents its metadata clock as UTC; preserve that convention
        # while keeping the raw upstream value for later audit.
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def parse_aisstream_message(payload: dict[str, Any], *, received_at: str | None = None) -> dict[str, Any] | None:
    """Normalize AISStream-style websocket payloads without hiding source defects.

    Source timestamps are preserved verbatim. ``observed_at`` uses a valid upstream
    timestamp when available and otherwise falls back to the local receive clock. This
    keeps BigQuery rows queryable while allowing the quality engine to quarantine an
    invalid upstream clock instead of silently replacing it.

    Port, terminal and geofence state are intentionally not inferred here.
    """
    if not isinstance(payload, dict):
        return None
    meta = payload.get("MetaData") or payload.get("metadata") or {}
    message = payload.get("Message") or payload.get("message") or {}
    msg_type = payload.get("MessageType") or payload.get("messageType") or ""
    if not isinstance(meta, dict) or not isinstance(message, dict):
        return None

    body = message.get(msg_type) if msg_type in message else None
    if not isinstance(body, dict):
        body = next((v for v in message.values() if isinstance(v, dict)), message)
    if not isinstance(body, dict):
        return None

    mmsi = _first(meta, "MMSI", "Mmsi") or _first(body, "UserID", "MMSI", "Mmsi")
    if not mmsi:
        return None

    source_timestamp = _first(meta, "time_utc", "TimeUtc", "Timestamp")
    source_dt = _parse_timestamp(source_timestamp)
    received_dt = _parse_timestamp(received_at) or _utc_now()
    observed_dt = source_dt or received_dt

    normalized = {
        "message_type": str(msg_type or "UNKNOWN"),
        "mmsi": str(mmsi),
        "imo": str(_first(meta, "IMO", "Imo") or _first(body, "ImoNumber", "IMO") or "") or None,
        "vessel_name": _first(meta, "ShipName", "Name") or _first(body, "Name", "ShipName"),
        "observed_at": observed_dt.isoformat(),
        "source_timestamp_raw": None if source_timestamp in (None, "") else str(source_timestamp),
        "received_at": received_dt.isoformat(),
        "timestamp_basis": "SOURCE" if source_dt is not None else "RECEIVED",
        "latitude": _float(_first(meta, "latitude", "Latitude") or _first(body, "Latitude")),
        "longitude": _float(_first(meta, "longitude", "Longitude") or _first(body, "Longitude")),
        "sog_kn": _float(_first(body, "Sog", "SpeedOverGround")),
        "cog_deg": _float(_first(body, "Cog", "CourseOverGround")),
        "navigation_status": _first(body, "NavigationalStatus", "NavigationStatus"),
        "destination": _first(body, "Destination"),
        "source_id": "aisstream",
    }
    return normalized
