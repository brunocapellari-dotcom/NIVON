# Reused from AgroLogMT/collector/ais_stream_client.py; verify provenance/license before commercial release.
from __future__ import annotations

import json
import random
import time
from collections.abc import Callable, Iterator
from typing import Any
from urllib.parse import urlsplit

from nivon.maritime.ais_stream import build_subscription, parse_aisstream_message


AISSTREAM_URL = "wss://stream.aisstream.io/v0/stream"
AISSTREAM_HOST = "stream.aisstream.io"


def _validate_stream_url(url: str) -> None:
    parsed = urlsplit(url)
    if parsed.scheme != "wss" or parsed.hostname != AISSTREAM_HOST or parsed.username or parsed.password:
        raise ValueError("AISStream exige WSS no host oficial stream.aisstream.io")


def stream_once(
    *,
    api_key: str,
    bounding_boxes: list[list[list[float]]],
    mmsi_filter: list[str] | None = None,
    max_messages: int | None = None,
    max_seconds: float | None = None,
    url: str = AISSTREAM_URL,
    heartbeat_seconds: float = 30.0,
    on_heartbeat: Callable[[dict[str, Any]], None] | None = None,
) -> Iterator[dict[str, Any]]:
    """Open one AISStream connection and yield normalized AIS records.

    Raw JSON is attached because the upstream service has no durable replay.
    Heartbeats are operational telemetry, not source offsets. max_seconds permits
    bounded Cloud Run capture windows while preserving reconnect between windows.
    """
    try:
        from websockets.sync.client import connect
    except ImportError as exc:  # pragma: no cover
        raise RuntimeError("instale websockets>=15,<16 para AIS live") from exc

    _validate_stream_url(url)
    subscription = build_subscription(api_key, bounding_boxes, mmsi_filter)
    count = 0
    deadline = time.monotonic() + max_seconds if max_seconds is not None else None
    heartbeat_seconds = max(5.0, float(heartbeat_seconds))
    next_heartbeat = time.monotonic() + heartbeat_seconds

    with connect(
        url,
        compression="deflate",
        open_timeout=15,
        close_timeout=5,
        ping_interval=20,
        ping_timeout=20,
    ) as ws:
        ws.send(json.dumps(subscription, separators=(",", ":")))
        while True:
            now = time.monotonic()
            if deadline is not None and now >= deadline:
                return
            timeout = min(5.0, max(0.1, next_heartbeat - now))
            if deadline is not None:
                timeout = max(0.1, min(timeout, deadline - now))
            try:
                frame = ws.recv(timeout=timeout)
            except TimeoutError:
                now = time.monotonic()
                if on_heartbeat is not None and now >= next_heartbeat:
                    on_heartbeat({"event": "HEARTBEAT", "records_seen": count})
                    next_heartbeat = now + heartbeat_seconds
                if deadline is not None and now >= deadline:
                    return
                continue
            if frame is None:
                return
            if isinstance(frame, bytes):
                frame = frame.decode("utf-8")
            payload = json.loads(frame)
            if payload.get("MessageType") == "SubscriptionConfirmation":
                continue
            row = parse_aisstream_message(payload)
            if row is None:
                continue
            row["_raw_message"] = payload
            yield row
            count += 1
            now = time.monotonic()
            if on_heartbeat is not None and now >= next_heartbeat:
                on_heartbeat({"event": "HEARTBEAT", "records_seen": count})
                next_heartbeat = now + heartbeat_seconds
            if max_messages is not None and count >= max_messages:
                return


def run_forever(
    *,
    api_key: str,
    bounding_boxes: list[list[list[float]]],
    on_record: Callable[[dict[str, Any]], None],
    mmsi_filter: list[str] | None = None,
    stop_after_records: int | None = None,
    stop_after_seconds: float | None = None,
    base_backoff_seconds: float = 1.0,
    max_backoff_seconds: float = 60.0,
    heartbeat_seconds: float = 30.0,
    on_heartbeat: Callable[[dict[str, Any]], None] | None = None,
    on_reconnect: Callable[[dict[str, Any]], None] | None = None,
) -> int:
    """Reconnect with bounded exponential backoff until record/time limit is reached."""
    delivered = 0
    failures = 0
    overall_deadline = time.monotonic() + stop_after_seconds if stop_after_seconds is not None else None
    while stop_after_records is None or delivered < stop_after_records:
        if overall_deadline is not None and time.monotonic() >= overall_deadline:
            break
        remaining_records = None if stop_after_records is None else stop_after_records - delivered
        remaining_seconds = None if overall_deadline is None else max(0.0, overall_deadline - time.monotonic())
        try:
            for row in stream_once(
                api_key=api_key,
                bounding_boxes=bounding_boxes,
                mmsi_filter=mmsi_filter,
                max_messages=remaining_records,
                max_seconds=remaining_seconds,
                heartbeat_seconds=heartbeat_seconds,
                on_heartbeat=on_heartbeat,
            ):
                on_record(row)
                delivered += 1
            failures = 0
        except (OSError, TimeoutError, ConnectionError, json.JSONDecodeError) as exc:
            failures += 1
            delay = min(max_backoff_seconds, base_backoff_seconds * (2 ** min(failures - 1, 8)))
            if overall_deadline is not None:
                delay = min(delay, max(0.0, overall_deadline - time.monotonic()))
            if on_reconnect is not None:
                on_reconnect({
                    "event": "RECONNECT",
                    "failure_count": failures,
                    "error_type": type(exc).__name__,
                    "backoff_seconds": delay,
                    "records_delivered": delivered,
                })
            if delay <= 0:
                break
            time.sleep(delay * (0.75 + random.random() * 0.5))
    return delivered
