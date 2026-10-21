# Adapted from AgroLogMT/models/maritime_source_health.py (main 2026-10-19); review provenance before external release.
from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from typing import Any


@dataclass(frozen=True)
class SourceHealth:
    source_id: str
    status: str
    transport_status: str
    data_status: str
    last_success_at: str | None
    last_record_at: str | None
    collector_age_minutes: float | None
    data_age_minutes: float | None
    flags: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _utc(value: datetime | str | None) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        parsed = value
    else:
        try:
            parsed = datetime.fromisoformat(str(value).strip().replace("Z", "+00:00"))
        except ValueError:
            return None
    if parsed.tzinfo is None:
        return None
    return parsed.astimezone(timezone.utc)


def _age_minutes(now: datetime, value: datetime | None) -> float | None:
    if value is None:
        return None
    return max(0.0, (now - value).total_seconds() / 60.0)


def assess_source_health(
    *,
    source_id: str,
    now: datetime | str,
    expected_interval_minutes: float,
    last_success_at: datetime | str | None,
    last_record_at: datetime | str | None,
    last_error_at: datetime | str | None = None,
    source_mode: str = "PERIODIC",
) -> SourceHealth:
    """Separate collector transport health from freshness of source data.

    A successful scrape with no new source record is not called a network failure.
    Conversely, fresh historical data cannot hide a dead collector. This distinction
    avoids presenting source lag as a system outage or stale cache as fresh collection.
    """
    now_utc = _utc(now)
    if now_utc is None:
        raise ValueError("now deve ser timezone-aware")
    interval = float(expected_interval_minutes)
    if interval <= 0:
        raise ValueError("expected_interval_minutes deve ser > 0")

    success = _utc(last_success_at)
    record = _utc(last_record_at)
    error = _utc(last_error_at)
    flags: list[str] = []
    collector_age = _age_minutes(now_utc, success)
    data_age = _age_minutes(now_utc, record)

    if success is None:
        transport_status = "NEVER_SUCCEEDED"
    elif error is not None and error > success:
        transport_status = "ERROR_AFTER_LAST_SUCCESS"
        flags.append("collector_error_after_success")
    elif collector_age is not None and collector_age > interval * 2.5:
        transport_status = "STALE_COLLECTOR"
        flags.append("collector_missed_expected_window")
    else:
        transport_status = "HEALTHY"

    mode = str(source_mode).strip().upper()
    if record is None:
        data_status = "NO_DATA"
        flags.append("no_source_record")
    elif data_age is not None and data_age <= interval * 1.5:
        data_status = "FRESH"
    elif data_age is not None and data_age <= interval * 3.0:
        data_status = "DELAYED"
        flags.append("source_data_delayed")
    else:
        data_status = "STALE"
        flags.append("source_data_stale")

    if mode == "EVENT_DRIVEN" and data_status in {"DELAYED", "STALE"} and transport_status == "HEALTHY":
        flags.append("event_source_may_have_no_new_event")

    if transport_status in {"NEVER_SUCCEEDED", "ERROR_AFTER_LAST_SUCCESS", "STALE_COLLECTOR"}:
        status = "UNHEALTHY"
    elif data_status == "FRESH":
        status = "FRESH"
    elif data_status == "DELAYED":
        status = "DELAYED"
    elif data_status == "STALE":
        status = "STALE"
    else:
        status = "NO_DATA"

    return SourceHealth(
        source_id=source_id,
        status=status,
        transport_status=transport_status,
        data_status=data_status,
        last_success_at=success.isoformat() if success else None,
        last_record_at=record.isoformat() if record else None,
        collector_age_minutes=collector_age,
        data_age_minutes=data_age,
        flags=tuple(sorted(set(flags))),
    )
