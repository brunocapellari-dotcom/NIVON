# Tests adapted from AgroLogMT/tests/test_maritime_weather.py (2026-10-19).
import unittest

from nivon.maritime.maritime_weather import (
    MaritimeWeatherRecord,
    PortWeatherThresholds,
    assess_maritime_weather,
)


class MaritimeWeatherTests(unittest.TestCase):
    def test_no_thresholds_means_exposure_only(self):
        result = assess_maritime_weather(MaritimeWeatherRecord(
            source_id="weather",
            valid_at="2026-09-15T12:00:00+00:00",
            evidence_class="OBSERVADO",
            wind_kn=25,
            wave_height_m=2.0,
        ))
        self.assertEqual(result.status, "EXPOSURE_ONLY")
        self.assertFalse(result.restrictions_claimed)

    def test_unofficial_threshold_cannot_claim_port_restriction(self):
        result = assess_maritime_weather(
            MaritimeWeatherRecord(
                source_id="weather",
                valid_at="2026-09-15T12:00:00+00:00",
                evidence_class="OBSERVADO",
                wind_kn=35,
            ),
            thresholds=PortWeatherThresholds(source_id="research", max_wind_kn=20),
        )
        self.assertEqual(result.status, "THRESHOLD_COMPARISON_ONLY")
        self.assertIn("wind_kn", result.exceeded)
        self.assertFalse(result.restrictions_claimed)

    def test_authorized_rule_can_raise_operational_limit_alert(self):
        result = assess_maritime_weather(
            MaritimeWeatherRecord(
                source_id="official-weather",
                valid_at="2026-09-15T12:00:00+00:00",
                evidence_class="OBSERVADO",
                wind_kn=30,
                visibility_km=1.5,
            ),
            thresholds=PortWeatherThresholds(
                source_id="port-rule",
                max_wind_kn=25,
                min_visibility_km=2.0,
                authorized_operational_rule=True,
            ),
        )
        self.assertEqual(result.status, "AUTHORIZED_LIMIT_EXCEEDED")
        self.assertTrue(result.restrictions_claimed)
        self.assertEqual(set(result.exceeded), {"wind_kn", "visibility_km"})

    def test_negative_physical_value_fails_closed(self):
        with self.assertRaises(ValueError):
            assess_maritime_weather(MaritimeWeatherRecord(
                source_id="weather",
                valid_at="2026-09-15T12:00:00+00:00",
                evidence_class="OBSERVADO",
                wave_height_m=-1,
            ))


if __name__ == "__main__":
    unittest.main()
