# Reused from AgroLogMT/tests/test_ais_quality.py; verify provenance/license before commercial release.
import unittest
from datetime import datetime, timezone

from nivon.maritime.ais_quality import assess_ais_record, valid_imo, valid_mmsi


class AisQualityTests(unittest.TestCase):
    def test_mmsi_and_imo_validation(self):
        self.assertTrue(valid_mmsi("710123456"))
        self.assertFalse(valid_mmsi("123"))
        self.assertTrue(valid_imo("9074729"))
        self.assertFalse(valid_imo("9074728"))

    def test_single_message_is_never_corroborated(self):
        row = {
            "mmsi": "710123456",
            "imo": "9074729",
            "observed_at": "2026-09-14T12:00:00+00:00",
            "latitude": -24.0,
            "longitude": -46.3,
        }
        result = assess_ais_record(
            row,
            same_identity_message_count=1,
            now=datetime(2026, 9, 14, 12, 1, tzinfo=timezone.utc),
        )
        self.assertEqual(result.quality_status, "UNCONFIRMED_SINGLE")
        self.assertFalse(result.corroborated)

    def test_impossible_track_is_quarantined(self):
        previous = {
            "mmsi": "710123456",
            "imo": "9074729",
            "message_type": "PositionReport",
            "observed_at": "2026-09-14T12:00:00+00:00",
            "latitude": -24.0,
            "longitude": -46.3,
        }
        current = {
            "mmsi": "710123456",
            "imo": "9074729",
            "message_type": "PositionReport",
            "observed_at": "2026-09-14T12:05:00+00:00",
            "latitude": -23.0,
            "longitude": -45.0,
        }
        result = assess_ais_record(
            current,
            previous=previous,
            same_identity_message_count=2,
            now=datetime(2026, 9, 14, 12, 6, tzinfo=timezone.utc),
        )
        self.assertEqual(result.quality_status, "QUARANTINE")
        self.assertIn("impossible_speed", result.flags)
        self.assertIn("teleport", result.flags)
        self.assertTrue(result.spoofing_suspected)

    def test_identity_conflict_is_quarantined(self):
        previous = {
            "mmsi": "710123456",
            "imo": "9074729",
            "observed_at": "2026-09-14T12:00:00+00:00",
            "latitude": -24.0,
            "longitude": -46.3,
        }
        current = {
            "mmsi": "710123456",
            "imo": "9319466",
            "observed_at": "2026-09-14T12:05:00+00:00",
            "latitude": -24.001,
            "longitude": -46.301,
        }
        result = assess_ais_record(
            current,
            previous=previous,
            same_identity_message_count=2,
            now=datetime(2026, 9, 14, 12, 6, tzinfo=timezone.utc),
        )
        self.assertEqual(result.quality_status, "QUARANTINE")
        self.assertIn("identity_conflict_mmsi_to_imo", result.flags)


if __name__ == "__main__":
    unittest.main()
