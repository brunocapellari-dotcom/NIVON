# Tests adapted from AgroLogMT/tests/test_shipping_pipeline.py (2026-10-19).
import unittest
from datetime import datetime, timezone

from nivon.maritime.shipping_pipeline import reconcile_lineup_snapshot, reconciliation_alerts, snapshot_summary
from nivon.maritime.shipping_reconciliation import AISObservation, LineupCall, PortOperation


UTC = timezone.utc


def t(day, hour=0):
    return datetime(2026, 8, day, hour, tzinfo=UTC)


class ShippingPipelineTest(unittest.TestCase):
    def test_batch_reconciliation_and_summary(self):
        calls = [
            LineupCall("C1", "SANTOS", "AGRO 1", t(20, 12), t(18), imo="9000001"),
            LineupCall("C2", "SANTOS", "AGRO 2", t(20, 12), t(18), imo="9000002"),
        ]
        ais = [
            AISObservation(t(20, 13), imo="9000001", vessel_name="AGRO 1", port_id="SANTOS", zone="ANCHORAGE"),
        ]
        operations = [
            PortOperation("C1", "SANTOS", "spa", actual_arrival_at=t(20, 13), completed_at=t(21), operation_status="COMPLETED")
        ]
        rows = reconcile_lineup_snapshot(calls, ais, operations)
        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[0].state, "COMPLETED_REALIZED")
        self.assertEqual(rows[1].state, "PROGRAMMED")
        summary = snapshot_summary(rows)
        self.assertEqual(summary["calls"], 2)
        self.assertEqual(summary["states"]["COMPLETED_REALIZED"], 1)
        self.assertGreaterEqual(summary["alerts"], 1)

    def test_delay_alert(self):
        call = LineupCall("C1", "SANTOS", "AGRO 1", t(20, 0), t(18), imo="9000001")
        ais = [AISObservation(t(22, 2), imo="9000001", vessel_name="AGRO 1", port_id="SANTOS", zone="ANCHORAGE")]
        rows = reconcile_lineup_snapshot([call], ais)
        alerts = reconciliation_alerts(rows, eta_delay_hours=24)
        self.assertTrue(any(a["type"] == "ETA_DELAY" for a in alerts))


if __name__ == "__main__":
    unittest.main()
