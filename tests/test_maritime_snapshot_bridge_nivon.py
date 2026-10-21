"""E2E offline AIS -> coordenador -> snapshot auditado -> cockpit read-only."""
import unittest
from dataclasses import replace
from datetime import datetime, timedelta, timezone

from nivon.maritime.intelligence import MaritimeAnalysisRequest, MaritimeIntelligenceCoordinator
from nivon.maritime.maritime_gateway import MaritimeReadAPI, MaritimeInternalSnapshot
from nivon.maritime.port_geofence import PortZone
from nivon.maritime.shipping_reconciliation import LineupCall

NOW = datetime.now(timezone.utc)
ZONE = PortZone(
    zone_id="SYNTHETIC_Z1", port_id="SANTOS", zone="ANCHORAGE",
    polygon=((-24.1,-46.6),(-24.1,-46.2),(-23.7,-46.2),(-23.7,-46.6)),
    geofence_version="TEST_ONLY", source_id="SYNTHETIC_GEOFENCE",
)


def ais(minutes, lat=-23.90, lon=-46.40):
    return {
        "message_type": "PositionReport", "mmsi": "123456789",
        "vessel_name": "NAVIO FICTICIO",
        "observed_at": (NOW - timedelta(minutes=minutes)).isoformat(),
        "latitude": lat, "longitude": lon, "sog_kn": 1.1,
    }


def request(**overrides):
    data = dict(
        port_id="SANTOS", now=NOW,
        ais_records=(ais(4), ais(2, lat=-23.9001)),
        geofences=(ZONE,), geofences_validated=True,
        ais_collection_authorized=True, source_id="SIMULATED",
        source_last_success_at=NOW.isoformat(),
        source_last_record_at=(NOW-timedelta(minutes=2)).isoformat(),
    )
    data.update(overrides)
    return MaritimeAnalysisRequest(**data)


class TestMaritimeSnapshotBridge(unittest.TestCase):
    def test_corroborated_position_is_shadow_not_live(self):
        report = MaritimeIntelligenceCoordinator().run(request())
        self.assertEqual(report["evidence"]["ais_trusted_in_port"], 1)
        self.assertEqual(len(report["trusted_positions_internal_only"]), 1)
        view = MaritimeInternalSnapshot.from_analysis(report)
        api = MaritimeReadAPI(internal=view)
        code, result = api.resolve("/v1/maritime/vessels", "port_id=SANTOS&hours=6")
        self.assertEqual(code, 200)
        self.assertEqual(result["status"], "SHADOW_INTERNAL")
        self.assertFalse(result["publication_allowed"])
        self.assertEqual(len(result["data"]), 1)
        self.assertEqual(result["data"][0]["quality_status"], "CONFIRMED_SEQUENCE")
        code, summary = api.resolve("/v1/maritime/summary", "port_id=SANTOS")
        self.assertEqual(summary["data"]["vessels_waiting"], 1)
        self.assertFalse(summary["publication_allowed"])

    def test_no_data_or_rights_cannot_become_internal_view(self):
        for req in (request(ais_records=()), request(ais_collection_authorized=False),
                    request(geofences_validated=False), request(source_last_success_at=None)):
            report = MaritimeIntelligenceCoordinator().run(req)
            self.assertFalse(report["trusted_positions_internal_only"])
            with self.assertRaises(ValueError):
                MaritimeInternalSnapshot.from_analysis(report)

    def test_cannot_promote_forged_published_report(self):
        report = MaritimeIntelligenceCoordinator().run(request())
        report["publication_allowed"] = True
        with self.assertRaises(ValueError):
            MaritimeInternalSnapshot.from_analysis(report)

    def test_lineup_stays_programmed_even_with_ais(self):
        lineup = LineupCall(
            call_id="CALL1", port_id="SANTOS", vessel_name="NAVIO FICTICIO",
            eta=NOW.isoformat(), collected_at=NOW.isoformat(),
            planned_volume_t=15000.0, source_id="LINEUP_FIXTURE",
        )
        report = MaritimeIntelligenceCoordinator().run(request(
            lineup_calls=(lineup,), lineup_authorized=True,
        ))
        snap = MaritimeInternalSnapshot.from_analysis(report, lineup_calls=(lineup,))
        code, r = MaritimeReadAPI(internal=snap).resolve(
            "/v1/maritime/lineup", "port_id=SANTOS",
        )
        self.assertEqual(code, 200)
        self.assertEqual(len(r["data"]), 1)
        self.assertNotEqual(r["data"][0]["reconciled_state"], "COMPLETED_REALIZED")
        self.assertEqual(r["data"][0]["evidence_class"], "INFORMADO_LINEUP")

    def test_unapproved_lineup_cannot_be_exposed(self):
        lineup = LineupCall(
            call_id="CALL1", port_id="SANTOS", vessel_name="NAVIO FICTICIO",
            eta=NOW.isoformat(), collected_at=NOW.isoformat(),
        )
        report = MaritimeIntelligenceCoordinator().run(request(
            lineup_calls=(lineup,), lineup_authorized=False,
        ))
        with self.assertRaises(ValueError):
            MaritimeInternalSnapshot.from_analysis(report, lineup_calls=(lineup,))

    def test_cannot_mix_shadow_fixture_with_audited_snapshot(self):
        report = MaritimeIntelligenceCoordinator().run(request())
        view = MaritimeInternalSnapshot.from_analysis(report)
        from nivon.maritime.maritime_gateway import MaritimeShadowFixture
        with self.assertRaises(ValueError):
            MaritimeReadAPI(internal=view, fixture=MaritimeShadowFixture())


if __name__ == "__main__":
    unittest.main()
