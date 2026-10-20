"""Regressao offline E2E: orquestracao maritima NIVON, com fixtures 100% sinteticas."""
import unittest
from datetime import datetime, timedelta, timezone

from nivon.maritime.intelligence import MaritimeAnalysisRequest, MaritimeIntelligenceCoordinator
from nivon.maritime.port_geofence import PortZone
from nivon.maritime.shipping_reconciliation import LineupCall

NOW = datetime(2026, 10, 19, 15, 0, tzinfo=timezone.utc)
ZONE = PortZone(
    zone_id="TEST_ANCHORAGE", port_id="PORTO_TESTE", zone="ANCHORAGE",
    polygon=((-13.1, -56.1), (-13.1, -55.9), (-12.9, -55.9), (-12.9, -56.1)),
    geofence_version="synthetic-v1", source_id="SYNTHETIC_FIXTURE",
)


def ais(timestamp, *, lat=-13.0, lon=-56.0, mmsi="123456789"):
    return {
        "message_type": "PositionReport", "observed_at": timestamp.isoformat(),
        "mmsi": mmsi, "latitude": lat, "longitude": lon, "sog_kn": 1.2,
        "vessel_name": "NAVIO SIMULADO",
    }


class TestMaritimeCoordinator(unittest.TestCase):
    def setUp(self):
        self.engine = MaritimeIntelligenceCoordinator()

    @staticmethod
    def request(**kwargs):
        arguments = {"port_id": "PORTO_TESTE", "now": NOW, "source_id": "AIS_FIXTURE"}
        arguments.update(kwargs)
        return MaritimeAnalysisRequest(**arguments)

    def test_no_data_is_unknown_not_zero(self):
        result = self.engine.run(self.request())
        self.assertEqual(result["evidence"]["ais_trusted_in_port"], 0)
        self.assertIsNone(result["queue"])
        self.assertIsNone(result["queue_forecast"])
        self.assertEqual(result["release"]["status"], "BLOCKED")
        self.assertFalse(result["publication_allowed"])

    def test_source_rights_block_physical_states(self):
        result = self.engine.run(self.request(
            geofences=(ZONE,), geofences_validated=True,
            ais_records=(ais(NOW-timedelta(minutes=4)), ais(NOW-timedelta(minutes=2))),
        ))
        self.assertEqual(result["evidence"]["ais_trusted_in_port"], 0)
        self.assertIsNone(result["queue"])

    def test_duplicated_message_is_not_corroboration(self):
        msg = ais(NOW-timedelta(minutes=2))
        result = self.engine.run(self.request(
            geofences=(ZONE,), geofences_validated=True, ais_collection_authorized=True,
            source_last_success_at=NOW.isoformat(), source_last_record_at=NOW.isoformat(),
            ais_records=(msg, msg),
        ))
        self.assertEqual(result["evidence"]["ais_duplicates_rejected"], 1)
        self.assertEqual(result["evidence"]["ais_trusted_in_port"], 0)

    def test_corroboration_then_queue_requires_history(self):
        result = self.engine.run(self.request(
            geofences=(ZONE,), geofences_validated=True, ais_collection_authorized=True,
            source_last_success_at=NOW.isoformat(),
            source_last_record_at=(NOW-timedelta(minutes=2)).isoformat(),
            ais_records=(
                ais(NOW-timedelta(minutes=4)),
                ais(NOW-timedelta(minutes=2), lat=-13.0001, lon=-56.0001),
            ),
        ))
        self.assertEqual(result["evidence"]["ais_trusted_in_port"], 1)
        self.assertEqual(result["queue"]["status"], "DATA_GATED")
        self.assertEqual(result["queue_forecast"]["status"], "DATA_GATED")
        self.assertFalse(result["publication_allowed"])

    def test_lineup_completed_does_not_claim_realized(self):
        call = LineupCall(
            call_id="1", port_id="PORTO_TESTE", vessel_name="NAVIO SIMULADO",
            eta=NOW.isoformat(), collected_at=NOW.isoformat(),
            planned_volume_t=10000.0, lineup_status="COMPLETED",
        )
        result = self.engine.run(self.request(
            lineup_calls=(call,), lineup_authorized=True,
        ))
        self.assertEqual(len(result["reconciliation"]), 1)
        self.assertNotEqual(result["reconciliation"][0]["state"], "COMPLETED_REALIZED")
        self.assertFalse(result["publication_allowed"])

    def test_invalid_mmsi_is_quarantined(self):
        result = self.engine.run(self.request(
            ais_records=(ais(NOW, mmsi="BAD"),),
        ))
        self.assertEqual(
            result["evidence"]["ais_quality"][0]["quality"]["quality_status"],
            "QUARANTINE",
        )

    def test_naive_timestamp_rejected(self):
        with self.assertRaises(ValueError):
            self.engine.run(self.request(now="2026-10-19T15:00:00"))

    def test_geofence_without_provenance_rejected(self):
        bad = PortZone(
            zone_id="BAD", port_id="PORTO_TESTE", zone="ANCHORAGE",
            polygon=ZONE.polygon, geofence_version="1", source_id=None,
        )
        with self.assertRaises(ValueError):
            self.engine.run(self.request(
                geofences=(bad,), geofences_validated=True,
            ))

    def test_other_port_lineup_rejected(self):
        call = LineupCall(
            call_id="other", port_id="OUTRO_PORTO",
            vessel_name="NAVIO SIMULADO", eta=NOW.isoformat(),
            collected_at=NOW.isoformat(),
        )
        with self.assertRaises(ValueError):
            self.engine.run(self.request(lineup_calls=(call,)))

    def test_large_batch_rejected(self):
        with self.assertRaises(ValueError):
            self.engine.run(self.request(ais_records=({},)*50001))


if __name__ == "__main__":
    unittest.main()
