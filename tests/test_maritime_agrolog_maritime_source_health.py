# Tests adapted from AgroLogMT/tests/test_maritime_source_health.py (2026-10-19).
import unittest

from nivon.maritime.maritime_source_health import assess_source_health


class MaritimeSourceHealthTests(unittest.TestCase):
    def test_healthy_collector_and_fresh_data_are_fresh(self):
        result = assess_source_health(
            source_id="aisstream",
            now="2026-09-15T12:00:00+00:00",
            expected_interval_minutes=60,
            last_success_at="2026-09-15T11:40:00+00:00",
            last_record_at="2026-09-15T11:55:00+00:00",
        )
        self.assertEqual(result.status, "FRESH")
        self.assertEqual(result.transport_status, "HEALTHY")
        self.assertEqual(result.data_status, "FRESH")

    def test_transport_failure_is_not_hidden_by_recent_data(self):
        result = assess_source_health(
            source_id="lineup",
            now="2026-09-15T12:00:00+00:00",
            expected_interval_minutes=60,
            last_success_at="2026-09-15T09:00:00+00:00",
            last_record_at="2026-09-15T11:30:00+00:00",
        )
        self.assertEqual(result.status, "UNHEALTHY")
        self.assertEqual(result.transport_status, "STALE_COLLECTOR")
        self.assertEqual(result.data_status, "FRESH")

    def test_source_lag_is_separate_from_collector_health(self):
        result = assess_source_health(
            source_id="port_authority",
            now="2026-09-15T12:00:00+00:00",
            expected_interval_minutes=60,
            last_success_at="2026-09-15T11:45:00+00:00",
            last_record_at="2026-09-15T06:00:00+00:00",
        )
        self.assertEqual(result.transport_status, "HEALTHY")
        self.assertEqual(result.data_status, "STALE")
        self.assertEqual(result.status, "STALE")
        self.assertIn("source_data_stale", result.flags)

    def test_event_source_no_new_record_is_not_called_network_outage(self):
        result = assess_source_health(
            source_id="port_alerts",
            now="2026-09-15T12:00:00+00:00",
            expected_interval_minutes=30,
            last_success_at="2026-09-15T11:50:00+00:00",
            last_record_at="2026-09-15T09:00:00+00:00",
            source_mode="EVENT_DRIVEN",
        )
        self.assertEqual(result.transport_status, "HEALTHY")
        self.assertIn("event_source_may_have_no_new_event", result.flags)

    def test_error_after_last_success_is_unhealthy(self):
        result = assess_source_health(
            source_id="comexstat",
            now="2026-09-15T12:00:00+00:00",
            expected_interval_minutes=1440,
            last_success_at="2026-09-15T08:00:00+00:00",
            last_record_at="2026-09-15T08:00:00+00:00",
            last_error_at="2026-09-15T10:00:00+00:00",
        )
        self.assertEqual(result.status, "UNHEALTHY")
        self.assertEqual(result.transport_status, "ERROR_AFTER_LAST_SUCCESS")


if __name__ == "__main__":
    unittest.main()
