# Tests adapted from AgroLogMT/tests/test_maritime_alerting.py (2026-10-19).
import unittest

from nivon.maritime.maritime_alerting import PriorAlert, alert_key, decide_alerts
from nivon.maritime.maritime_anomaly import MaritimeAnomaly


def anomaly(*, severity="HIGH", publication_status="ALERTABLE", anomaly_type="TEST"):
    return MaritimeAnomaly(
        anomaly_type=anomaly_type,
        severity=severity,
        confidence=0.9,
        evidence_class="INFERIDO",
        summary="test",
        evidence=("signal=x",),
        action="test",
        publication_status=publication_status,
    )


class MaritimeAlertingTests(unittest.TestCase):
    def test_hypothesis_is_routed_to_review_not_broadcast(self):
        decisions = decide_alerts(
            scope="SANTOS",
            anomalies=[anomaly(publication_status="HYPOTHESIS_ONLY", anomaly_type="AIS_SPOOFING_SUSPECTED")],
            now="2026-09-15T12:00:00+00:00",
        )
        self.assertEqual(decisions[0].action, "REVIEW_QUEUE")
        self.assertTrue(decisions[0].requires_human_review)

    def test_low_severity_is_suppressed(self):
        decision = decide_alerts(
            scope="SANTOS",
            anomalies=[anomaly(severity="LOW")],
            now="2026-09-15T12:00:00+00:00",
        )[0]
        self.assertEqual(decision.action, "SUPPRESS")

    def test_equivalent_alert_is_deduplicated_inside_cooldown(self):
        item = anomaly()
        key = alert_key(scope="SANTOS", anomaly=item)
        decision = decide_alerts(
            scope="SANTOS",
            anomalies=[item],
            now="2026-09-15T12:00:00+00:00",
            prior_alerts=[PriorAlert(key, "2026-09-15T11:30:00+00:00", "HIGH")],
            cooldown_minutes=60,
        )[0]
        self.assertEqual(decision.action, "DEDUP_COOLDOWN")

    def test_high_alert_outside_cooldown_passes(self):
        item = anomaly()
        key = alert_key(scope="SANTOS", anomaly=item)
        decision = decide_alerts(
            scope="SANTOS",
            anomalies=[item],
            now="2026-09-15T12:00:00+00:00",
            prior_alerts=[PriorAlert(key, "2026-09-15T09:00:00+00:00", "HIGH")],
            cooldown_minutes=60,
        )[0]
        self.assertEqual(decision.action, "ALERT")


if __name__ == "__main__":
    unittest.main()
