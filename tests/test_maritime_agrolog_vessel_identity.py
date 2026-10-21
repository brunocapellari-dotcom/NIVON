# Reused from AgroLogMT/tests/test_vessel_identity.py; verify provenance/license before commercial release.
import unittest

from nivon.maritime.vessel_identity import IdentityObservation, resolve_vessel_identity


class VesselIdentityTests(unittest.TestCase):
    def test_official_imo_wins_and_latest_mmsi_is_active(self):
        rows = [
            IdentityObservation("aisstream", "2026-01-01T00:00:00+00:00", imo="9074729", mmsi="710123456", vessel_name="MV AGRO STAR"),
            IdentityObservation("registry", "2026-06-01T00:00:00+00:00", imo="9074729", mmsi="710123456", vessel_name="AGRO STAR", official_registry=True),
            IdentityObservation("aisstream", "2026-09-01T00:00:00+00:00", imo="9074729", mmsi="710654321", vessel_name="AGRO STAR"),
        ]
        result = resolve_vessel_identity(rows)
        self.assertEqual(result.status, "RESOLVED_IMO")
        self.assertEqual(result.canonical_imo, "9074729")
        self.assertEqual(result.canonical_mmsi, "710654321")
        self.assertIn("mmsi_changed_for_imo", result.warnings)

    def test_recent_same_mmsi_multiple_imo_is_hard_conflict(self):
        rows = [
            IdentityObservation("aisstream", "2026-09-01T00:00:00+00:00", imo="9074729", mmsi="710123456", vessel_name="AGRO STAR"),
            IdentityObservation("aisstream", "2026-09-02T00:00:00+00:00", imo="9319466", mmsi="710123456", vessel_name="OTHER STAR"),
        ]
        result = resolve_vessel_identity(rows)
        self.assertEqual(result.status, "CONFLICT")
        self.assertTrue(any(item.startswith("mmsi_recent_multiple_imo") for item in result.conflicts))
        self.assertEqual(result.confidence, 0.0)

    def test_name_only_is_low_confidence_and_never_fuzzy_promoted(self):
        rows = [IdentityObservation("lineup", "2026-09-01T00:00:00+00:00", vessel_name="M/V TEST SHIP")]
        result = resolve_vessel_identity(rows)
        self.assertEqual(result.status, "NAME_ONLY")
        self.assertEqual(result.canonical_name, "TEST SHIP")
        self.assertLess(result.confidence, 0.8)

    def test_historical_mmsi_reuse_outside_window_is_not_hard_conflict(self):
        rows = [
            IdentityObservation("history", "2024-01-01T00:00:00+00:00", imo="9074729", mmsi="710123456"),
            IdentityObservation("aisstream", "2026-09-01T00:00:00+00:00", imo="9319466", mmsi="710123456"),
        ]
        result = resolve_vessel_identity(rows, conflict_window_days=90)
        self.assertNotEqual(result.status, "CONFLICT")


if __name__ == "__main__":
    unittest.main()
