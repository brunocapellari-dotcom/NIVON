"""Official programacao-only cockpit: date and event types cannot imply ship state."""
import unittest
from datetime import datetime, timezone, timedelta

from nivon.maritime.official_lineup_bridge import LineupBridgeResult
from nivon.maritime.maritime_gateway import (
    MaritimeProgrammedSnapshot, MaritimeReadAPI, MaritimeShadowFixture,
)
from nivon.maritime.shipping_reconciliation import LineupCall


def result():
    now = datetime.now(timezone.utc)
    eta = (now + timedelta(hours=5)).isoformat()
    captured = (now - timedelta(hours=1)).isoformat()
    call = LineupCall(
        call_id="SANTOS:APS_PROGRAMACAO:DUV123",
        port_id="SANTOS", vessel_name="CARGUEIRO TESTE",
        eta=eta,
        collected_at=captured,
        product="SOJA", planned_volume_t=15000.0,
        lineup_status="PROGRAMMED", source_id="APS_PROGRAMACAO",
    )
    return LineupBridgeResult(
        port_id="SANTOS", source_id="APS_PROGRAMACAO",
        source_url="https://www.portodesantos.com.br/oficial/",
        document_sha256="a"*64, collected_at=captured,
        candidates=(call,), excluded=(), source_rows=1,
    )


class TestProgrammedSnapshot(unittest.TestCase):
    def test_no_display_rights_rejected(self):
        with self.assertRaises(PermissionError):
            MaritimeProgrammedSnapshot.from_bridge(result())

    def test_programmed_without_ais_never_claims_zero_vessels(self):
        snap = MaritimeProgrammedSnapshot.from_bridge(result(), display_authorized=True)
        api = MaritimeReadAPI(programmed=snap)
        code, summary = api.resolve("/v1/maritime/summary", "port_id=SANTOS")
        self.assertEqual(code, 200)
        self.assertEqual(summary["status"], "SHADOW_LINEUP_ONLY")
        self.assertIsNone(summary["data"]["vessels_live"])
        self.assertIsNone(summary["data"]["vessels_waiting"])
        self.assertEqual(summary["data"]["lineup_calls"], 1)
        self.assertFalse(summary["publication_allowed"])
        code, ships = api.resolve("/v1/maritime/vessels", "port_id=SANTOS")
        self.assertEqual(ships["data"], [])
        code, lineup = api.resolve("/v1/maritime/lineup", "port_id=SANTOS")
        self.assertEqual(len(lineup["data"]), 1)
        self.assertEqual(lineup["data"][0]["reconciled_state"], "PROGRAMMED")
        self.assertEqual(lineup["data"][0]["evidence_class"], "PROGRAMADO_NAO_REALIZADO")

    def test_source_lineage_stays_attached(self):
        snap = MaritimeProgrammedSnapshot.from_bridge(result(), display_authorized=True)
        line = snap.lineup_rows[0]
        self.assertEqual(line["source_sha256"], "a"*64)
        self.assertEqual(line["source_id"], "APS_PROGRAMACAO")

    def test_invalid_state_prevents_display(self):
        invalid = result()
        from dataclasses import replace
        with self.assertRaises(ValueError):
            MaritimeProgrammedSnapshot.from_bridge(replace(invalid, state="LIVE"), display_authorized=True)
        with self.assertRaises(ValueError):
            MaritimeProgrammedSnapshot.from_bridge(replace(invalid, publication_allowed=True), display_authorized=True)

    def test_physical_status_is_rejected(self):
        from dataclasses import replace
        original = result()
        altered = replace(original.candidates[0], lineup_status="COMPLETED")
        with self.assertRaises(ValueError):
            MaritimeProgrammedSnapshot.from_bridge(
                replace(original, candidates=(altered,)), display_authorized=True,
            )

    def test_wrong_port_rejected(self):
        from dataclasses import replace
        original = result()
        altered = replace(original.candidates[0], port_id="ITAQUI")
        with self.assertRaises(ValueError):
            MaritimeProgrammedSnapshot.from_bridge(
                replace(original, candidates=(altered,)), display_authorized=True,
            )

    def test_cannot_mix_official_with_synthetic(self):
        snap = MaritimeProgrammedSnapshot.from_bridge(result(), display_authorized=True)
        with self.assertRaises(ValueError):
            MaritimeReadAPI(programmed=snap, fixture=MaritimeShadowFixture())

    def test_replay_is_empty_not_fabricated(self):
        snap = MaritimeProgrammedSnapshot.from_bridge(result(), display_authorized=True)
        code, replay = MaritimeReadAPI(programmed=snap).resolve(
            "/v1/maritime/vessels/123456789/replay", "hours=24"
        )
        self.assertEqual(code, 200)
        self.assertEqual(replay["data"], [])


if __name__ == "__main__":
    unittest.main()
