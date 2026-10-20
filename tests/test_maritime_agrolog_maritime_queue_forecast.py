# Tests adapted from AgroLogMT/tests/test_maritime_queue_forecast.py (2026-10-19).
import unittest

from nivon.maritime.maritime_queue_forecast import forecast_queue


class MaritimeQueueForecastTests(unittest.TestCase):
    def test_insufficient_history_is_data_gated(self):
        result = forecast_queue(
            current_waiting=5,
            arrivals_by_horizon={6: 2, 24: 5, 48: 8},
            historical_service_rates_per_hour=[0.2] * 10,
            geofences_validated=True,
            source_fresh=True,
        )
        self.assertEqual(result.status, "DATA_GATED")
        self.assertTrue(all(point.waiting_expected is None for point in result.points))

    def test_shadow_forecast_uses_mass_balance(self):
        rates = [0.25 + (index % 3) * 0.02 for index in range(60)]
        result = forecast_queue(
            current_waiting=6,
            arrivals_by_horizon={6: 2, 24: 5, 48: 9},
            historical_service_rates_per_hour=rates,
            geofences_validated=True,
            source_fresh=True,
        )
        self.assertEqual(result.status, "SHADOW_READY")
        self.assertEqual(result.publication_mode, "SHADOW")
        self.assertEqual([point.horizon_hours for point in result.points], [6, 24, 48])
        for point in result.points:
            self.assertLessEqual(point.waiting_low or 0, point.waiting_high or 0)

    def test_negative_arrivals_fail_closed(self):
        with self.assertRaises(ValueError):
            forecast_queue(
                current_waiting=2,
                arrivals_by_horizon={6: -1},
                historical_service_rates_per_hour=[0.2] * 40,
                geofences_validated=True,
                source_fresh=True,
            )


if __name__ == "__main__":
    unittest.main()
