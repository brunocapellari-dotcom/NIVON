# Tests adapted from AgroLogMT/tests/test_maritime_queue.py (2026-10-19).
import unittest

from nivon.maritime.maritime_queue import QueueSnapshot, evaluate_queue_pressure


class MaritimeQueueTests(unittest.TestCase):
    def test_missing_history_and_geofence_keeps_scores_gated(self):
        result = evaluate_queue_pressure(
            QueueSnapshot(4, 2, 1, (4.0, 8.0, 16.0), 5),
            historical_waiting_counts=(1, 2, 3),
            geofences_validated=False,
            source_fresh=True,
        )
        self.assertEqual(result.status, "DATA_GATED")
        self.assertIsNone(result.vqi)
        self.assertIn("geofences_not_validated", result.flags)
        self.assertIn("insufficient_history", result.flags)

    def test_fresh_validated_history_opens_shadow_only(self):
        history = tuple(float(i % 8) for i in range(60))
        result = evaluate_queue_pressure(
            QueueSnapshot(7, 3, 2, (8.0, 12.0, 18.0, 30.0), 9),
            historical_waiting_counts=history,
            geofences_validated=True,
            source_fresh=True,
            berth_capacity=4,
        )
        self.assertEqual(result.status, "SHADOW_READY")
        self.assertEqual(result.publication_mode, "SHADOW")
        self.assertIsNotNone(result.vqi)
        self.assertIsNotNone(result.port_pressure_score)
        self.assertGreater(result.historical_percentile or 0, 0.8)

    def test_missing_berth_capacity_does_not_invent_utilization(self):
        history = tuple(float(i % 5) for i in range(60))
        result = evaluate_queue_pressure(
            QueueSnapshot(3, 1, 1, (2.0, 5.0, 9.0), 2),
            historical_waiting_counts=history,
            geofences_validated=True,
            source_fresh=True,
        )
        self.assertEqual(result.status, "SHADOW_READY")
        self.assertIn("berth_capacity_missing", result.flags)
        self.assertAlmostEqual(result.port_pressure_score or 0, result.vqi or 0)

    def test_negative_counts_fail_closed(self):
        with self.assertRaises(ValueError):
            evaluate_queue_pressure(
                QueueSnapshot(-1, 0, 0, (), 0),
                historical_waiting_counts=tuple(range(30)),
                geofences_validated=True,
                source_fresh=True,
            )


if __name__ == "__main__":
    unittest.main()
