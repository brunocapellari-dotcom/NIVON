# Adapted from AgroLogMT/models/maritime_alerting.py (main 2026-10-19); review provenance before external release.
from __future__ import annotations

import hashlib
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Iterable

from nivon.maritime.maritime_anomaly import MaritimeAnomaly


_ALERTABLE_SEVERITIES = {"MEDIUM", "HIGH", "CRITICAL"}


@dataclass(frozen=True)
class PriorAlert:
    alert_key: str
    sent_at: str
    severity: str


@dataclass(frozen=True)
class AlertDecision:
    alert_key: str
    action: str
    severity: str
    reason: str
    anomaly_type: str
    evidence_class: str
    publication_status: str
    requires_human_review: bool

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _utc(value: datetime | str) -> datetime:
    if isinstance(value, datetime):
        parsed = value
    else:
        parsed = datetime.fromisoformat(str(value).strip().replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError("alert timestamp deve ter timezone")
    return parsed.astimezone(timezone.utc)


def alert_key(*, scope: str, anomaly: MaritimeAnomaly) -> str:
    payload = "|".join([
        str(scope).strip().upper(),
        anomaly.anomaly_type,
        anomaly.publication_status,
        ",".join(sorted(anomaly.evidence)),
    ])
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def decide_alerts(
    *,
    scope: str,
    anomalies: Iterable[MaritimeAnomaly],
    now: datetime | str,
    prior_alerts: Iterable[PriorAlert] = (),
    cooldown_minutes: int = 60,
) -> list[AlertDecision]:
    """Deterministic alert gate with idempotency/cooldown and evidence safeguards."""
    now_utc = _utc(now)
    cooldown = timedelta(minutes=max(0, int(cooldown_minutes)))
    prior = {item.alert_key: item for item in prior_alerts}
    decisions: list[AlertDecision] = []

    for anomaly in anomalies:
        key = alert_key(scope=scope, anomaly=anomaly)
        severity = anomaly.severity.upper()
        if severity not in _ALERTABLE_SEVERITIES:
            decisions.append(AlertDecision(
                alert_key=key,
                action="SUPPRESS",
                severity=severity,
                reason="below_alert_threshold",
                anomaly_type=anomaly.anomaly_type,
                evidence_class=anomaly.evidence_class,
                publication_status=anomaly.publication_status,
                requires_human_review=False,
            ))
            continue

        if anomaly.publication_status == "HYPOTHESIS_ONLY":
            decisions.append(AlertDecision(
                alert_key=key,
                action="REVIEW_QUEUE",
                severity=severity,
                reason="hypothesis_requires_independent_review",
                anomaly_type=anomaly.anomaly_type,
                evidence_class=anomaly.evidence_class,
                publication_status=anomaly.publication_status,
                requires_human_review=True,
            ))
            continue

        previous = prior.get(key)
        if previous is not None and now_utc - _utc(previous.sent_at) < cooldown:
            decisions.append(AlertDecision(
                alert_key=key,
                action="DEDUP_COOLDOWN",
                severity=severity,
                reason="equivalent_alert_inside_cooldown",
                anomaly_type=anomaly.anomaly_type,
                evidence_class=anomaly.evidence_class,
                publication_status=anomaly.publication_status,
                requires_human_review=False,
            ))
            continue

        decisions.append(AlertDecision(
            alert_key=key,
            action="ALERT",
            severity=severity,
            reason="policy_pass",
            anomaly_type=anomaly.anomaly_type,
            evidence_class=anomaly.evidence_class,
            publication_status=anomaly.publication_status,
            requires_human_review=severity == "CRITICAL",
        ))

    return decisions
