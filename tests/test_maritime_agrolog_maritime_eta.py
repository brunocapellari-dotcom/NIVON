# Tests adapted from AgroLogMT/tests/test_maritime_eta.py (2026-10-19).
import unittest

from nivon.maritime.maritime_eta import estimate_eta, eta_deviation_hours, great_circle_distance_nm


class MaritimeEtaTests(unittest.TestCase):
    def test_uncorroborated_ais_is_data_gated(self):
        result = estimate_eta(
            calculated_at="2026-09-15T12:00:00+00:00",
            distance_nm=100,
            distance_method="ROUTE_ENGINE",
            current_sog_kn=10,
            ais_corroborated=False,
        )
        self.assertEqual(result.status, "DATA_GATED")
        self.assertIn("ais_not_corroborated", result.flags)

    def test_route_eta_is_estimated_with_interval(self):
        result = estimate_eta(
            calculated_at="2026-09-15T12:00:00+00:00",
            distance_nm=120,
            distance_method="ROUTE_ENGINE",
            current_sog_kn=12,
            congestion_delay_hours=2,
        )
        self.assertEqual(result.status, "ESTIMATED")
        self.assertAlmostEqual(result.travel_hours or 0, 12.0)
        self.assertIsNotNone(result.eta_low)
        self.assertIsNotNone(result.eta_high)
        self.assertGreater(result.confidence, 0.7)

    def test_geodesic_is_explicit_low_confidence_lower_bound(self):
        distance = great_circle_distance_nm(-24.0, -46.3, -25.5, -48.5)
        result = estimate_eta(
            calculated_at="2026-09-15T12:00:00+00:00",
            distance_nm=distance,
            distance_method="GEODESIC_LOWER_BOUND",
            current_sog_kn=11,
        )
        self.assertEqual(result.status, "ESTIMATED")
        self.assertIn("geodesic_is_lower_bound_not_navigable_route", result.flags)
        self.assertLess(result.confidence, 0.7)

    def test_unapproved_distance_method_fails_closed(self):
        result = estimate_eta(
            calculated_at="2026-09-15T12:00:00+00:00",
            distance_nm=100,
            distance_method="MADE_UP_ROUTE",
            current_sog_kn=10,
        )
        self.assertEqual(result.status, "DATA_GATED")
        self.assertIn("distance_method_unapproved", result.flags)

    def test_eta_deviation_preserves_sign(self):
        self.assertAlmostEqual(
            eta_deviation_hours("2026-09-15T15:00:00+00:00", "2026-09-15T12:00:00+00:00") or 0,
            3.0,
        )


if __name__ == "__main__":
    unittest.main()
