# Tests adapted from AgroLogMT/tests/test_maritime_anomaly.py (2026-10-19).
import unittest

from nivon.maritime.maritime_anomaly import detect_maritime_anomalies


class MaritimeAnomalyTests(unittest.TestCase):
    def test_spoofing_is_never_called_confirmed(self):
        findings = detect_maritime_anomalies(
            ais_quality_flags=("teleport", "impossible_speed"),
            spoofing_suspected=True,
            corroborated_ais=True,
        )
        spoofing = next(item for item in findings if item.anomaly_type == "AIS_SPOOFING_SUSPECTED")
        self.assertEqual(spoofing.publication_status, "HYPOTHESIS_ONLY")
        self.assertEqual(spoofing.evidence_class, "INFERIDO")
        self.assertIn("não há confirmação", spoofing.summary)

    def test_unhealthy_source_blocks_dependents(self):
        findings = detect_maritime_anomalies(source_health_status="UNHEALTHY")
        self.assertEqual(len(findings), 1)
        self.assertEqual(findings[0].anomaly_type, "SOURCE_HEALTH")
        self.assertEqual(findings[0].severity, "HIGH")

    def test_eta_material_deviation_generates_alert(self):
        findings = detect_maritime_anomalies(eta_deviation_hours=15, corroborated_ais=True)
        eta = next(item for item in findings if item.anomaly_type == "ETA_DEVIATION")
        self.assertEqual(eta.severity, "MEDIUM")
        self.assertEqual(eta.evidence_class, "ESTIMADO")

    def test_queue_needs_explicit_historical_signal(self):
        self.assertFalse(any(
            item.anomaly_type == "PORT_QUEUE_PRESSURE"
            for item in detect_maritime_anomalies(queue_zscore=1.0, queue_percentile=0.50)
        ))
        findings = detect_maritime_anomalies(queue_zscore=2.5, queue_percentile=0.96)
        queue = next(item for item in findings if item.anomaly_type == "PORT_QUEUE_PRESSURE")
        self.assertEqual(queue.severity, "MEDIUM")

    def test_lineup_conflict_preserves_source_separation(self):
        findings = detect_maritime_anomalies(
            reconciliation_flags=("lineup_realized_not_confirmed",)
        )
        conflict = next(item for item in findings if item.anomaly_type == "AIS_LINEUP_CONFLICT")
        self.assertIn("não promover programação a realizado", conflict.action)


if __name__ == "__main__":
    unittest.main()
