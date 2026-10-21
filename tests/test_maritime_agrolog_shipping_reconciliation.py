# Tests adapted from AgroLogMT/tests/test_shipping_reconciliation.py (2026-10-19).
import unittest
from datetime import datetime, timezone

from nivon.maritime.ais_stream import build_subscription, parse_aisstream_message
from nivon.maritime.shipping_reconciliation import (
    AISObservation,
    LineupCall,
    PortOperation,
    lineup_reliability_score,
    match_lineup_call,
    normalize_vessel_name,
    reconcile_call,
)


UTC = timezone.utc


def ts(day: int, hour: int = 0):
    return datetime(2026, 8, day, hour, tzinfo=UTC)


class ShippingReconciliationTest(unittest.TestCase):
    def call(self, **kwargs):
        base = dict(
            call_id="CALL-1",
            port_id="SANTOS",
            terminal_id="T1",
            vessel_name="MV AGRO STAR",
            imo="9876543",
            mmsi="710123456",
            eta=ts(20, 12),
            collected_at=ts(18),
            product="SOJA",
            planned_volume_t=60000,
        )
        base.update(kwargs)
        return LineupCall(**base)

    def test_name_normalization(self):
        self.assertEqual(normalize_vessel_name("M/V Ágro-Star"), "AGRO STAR")

    def test_exact_imo_wins(self):
        obs = [AISObservation(ts(19), imo="9876543", mmsi="999", vessel_name="OTHER NAME")]
        match = match_lineup_call(self.call(), obs)
        self.assertTrue(match.matched)
        self.assertEqual(match.method, "IMO")
        self.assertEqual(match.confidence, 1.0)

    def test_conflicting_imo_blocks_fuzzy_match(self):
        obs = [AISObservation(ts(19), imo="1111111", vessel_name="AGRO STAR", port_id="SANTOS")]
        match = match_lineup_call(self.call(mmsi=None), obs)
        self.assertFalse(match.matched)

    def test_fuzzy_name_fallback(self):
        call = self.call(imo=None, mmsi=None)
        obs = [AISObservation(ts(20, 8), vessel_name="AGRO STAR", port_id="SANTOS", terminal_id="T1")]
        match = match_lineup_call(call, obs)
        self.assertTrue(match.matched)
        self.assertEqual(match.method, "NAME_FUZZY")
        self.assertGreater(match.confidence, 0.9)

    def test_ais_departure_is_not_realized(self):
        obs = [
            AISObservation(ts(20, 10), imo="9876543", mmsi="710123456", vessel_name="AGRO STAR", port_id="SANTOS", zone="ANCHORAGE"),
            AISObservation(ts(20, 16), imo="9876543", mmsi="710123456", vessel_name="AGRO STAR", port_id="SANTOS", terminal_id="T1", zone="BERTH"),
            AISObservation(ts(22, 5), imo="9876543", mmsi="710123456", vessel_name="AGRO STAR", port_id="SANTOS", zone="DEPARTED"),
        ]
        result = reconcile_call(self.call(), obs)
        self.assertEqual(result.state, "DEPARTED_PENDING_REALIZED")
        self.assertEqual(result.evidence_class, "AIS_OBSERVED")
        self.assertAlmostEqual(result.waiting_hours, 6.0)

    def test_berth_to_sea_transition_is_departure_pending_not_realized(self):
        obs = [
            AISObservation(ts(20, 10), imo="9876543", mmsi="710123456", vessel_name="AGRO STAR", port_id="SANTOS", zone="ANCHORAGE"),
            AISObservation(ts(20, 16), imo="9876543", mmsi="710123456", vessel_name="AGRO STAR", port_id="SANTOS", terminal_id="T1", zone="BERTH"),
            AISObservation(ts(21, 4), imo="9876543", mmsi="710123456", vessel_name="AGRO STAR", port_id=None, zone="SEA", sog_kn=9.0),
        ]
        result = reconcile_call(self.call(), obs)
        self.assertEqual(result.state, "DEPARTED_PENDING_REALIZED")
        self.assertEqual(result.evidence_class, "AIS_OBSERVED")
        self.assertIn("ais_departure_from_berth_exit_transition", result.flags)
        self.assertEqual(result.metadata["departure_detection"], "berth_exit_transition_upper_bound")
        self.assertAlmostEqual(result.berth_hours, 12.0)

    def test_port_operation_confirms_realized(self):
        obs = [
            AISObservation(ts(20, 10), imo="9876543", mmsi="710123456", vessel_name="AGRO STAR", port_id="SANTOS", zone="ANCHORAGE"),
            AISObservation(ts(20, 16), imo="9876543", mmsi="710123456", vessel_name="AGRO STAR", port_id="SANTOS", terminal_id="T1", zone="BERTH"),
            AISObservation(ts(22, 5), imo="9876543", mmsi="710123456", vessel_name="AGRO STAR", port_id="SANTOS", zone="DEPARTED"),
        ]
        operation = PortOperation(
            call_id="CALL-1",
            port_id="SANTOS",
            source_id="spa",
            actual_arrival_at=ts(20, 10),
            berth_at=ts(20, 16),
            unberth_at=ts(22, 5),
            completed_at=ts(22, 4),
            actual_volume_t=58500,
            operation_status="COMPLETED",
        )
        result = reconcile_call(self.call(), obs, operation)
        self.assertEqual(result.state, "COMPLETED_REALIZED")
        self.assertEqual(result.evidence_class, "PORT_OPERATION_OBSERVED")
        self.assertEqual(result.metadata["departure_detection"], "port_operation_observed")
        self.assertAlmostEqual(result.volume_variance_pct, -2.5)
        self.assertAlmostEqual(result.eta_error_hours, -2.0)

    def test_lineup_inconsistency_flag(self):
        call = self.call(lineup_status="BERTHED")
        obs = [AISObservation(ts(20, 13), imo="9876543", mmsi="710123456", vessel_name="AGRO STAR", port_id="SANTOS", zone="ANCHORAGE")]
        result = reconcile_call(call, obs)
        self.assertIn("lineup_says_berthed_but_ais_waiting", result.flags)

    def test_reliability_score(self):
        operation = PortOperation(
            call_id="CALL-1", port_id="SANTOS", source_id="spa",
            actual_arrival_at=ts(20, 12), berth_at=ts(20, 14),
            unberth_at=ts(21, 14), completed_at=ts(21, 13),
            actual_volume_t=60000, operation_status="COMPLETED",
        )
        obs = [AISObservation(ts(20, 12), imo="9876543", mmsi="710123456", vessel_name="AGRO STAR", port_id="SANTOS", zone="ANCHORAGE")]
        score = lineup_reliability_score([reconcile_call(self.call(), obs, operation)])
        self.assertEqual(score["score"], 100.0)

    def test_aisstream_parser(self):
        payload = {
            "MessageType": "PositionReport",
            "MetaData": {"MMSI": 710123456, "ShipName": "AGRO STAR", "latitude": -24.0, "longitude": -46.3, "time_utc": "2026-08-20T10:00:00Z"},
            "Message": {"PositionReport": {"Sog": 11.2, "Cog": 180.0, "NavigationalStatus": 0}},
        }
        row = parse_aisstream_message(payload)
        self.assertEqual(row["mmsi"], "710123456")
        self.assertEqual(row["vessel_name"], "AGRO STAR")
        self.assertEqual(row["sog_kn"], 11.2)

    def test_subscription(self):
        payload = build_subscription("secret", [[[-25.0, -47.0], [-23.0, -45.0]]], ["710123456"])
        self.assertEqual(payload["FiltersShipMMSI"], ["710123456"])


if __name__ == "__main__":
    unittest.main()
