"""Offline regression gates for maritime evidence, unique calls and AIS dwell.

No network access or operational data is required. All events are synthetic.
"""
import unittest

from nivon.maritime.port_call_engine import AisStatePoint, reconstruct_port_call
from nivon.maritime.shipping_pipeline import reconcile_lineup_snapshot
from nivon.maritime.shipping_reconciliation import (
    AISObservation,
    LineupCall,
    PortOperation,
    match_lineup_call,
    reconcile_call,
)


def ais_point(hour_minute, zone, suffix):
    return AisStatePoint(
        observed_at=f"2026-10-20T{hour_minute}:00+00:00",
        mmsi="710123456",
        port_id="SANTOS",
        zone=zone,
        quality_status="CONFIRMED_SEQUENCE",
        corroborated=True,
        observation_id=f"ais-{suffix}",
    )


def call():
    return LineupCall(
        call_id="DUV-001",
        port_id="SANTOS",
        vessel_name="MV TEST VESSEL",
        imo="9000001",
        mmsi="710123456",
        eta="2026-10-20T10:00:00+00:00",
        collected_at="2026-10-20T08:00:00+00:00",
    )


class MaritimeEventIntegrityTests(unittest.TestCase):
    def test_intervening_sea_point_breaks_anchorage_dwell(self):
        points = [
            ais_point("10:00", "ANCHORAGE", 1),
            ais_point("10:10", "SEA", 2),
            ais_point("10:35", "ANCHORAGE", 3),
        ]
        result = reconstruct_port_call(port_id="SANTOS", ais_points=points)
        states = {row.state for row in result.events}
        self.assertNotIn("FUNDEADO", states)
        self.assertNotIn("AGUARDANDO", states)

    def test_long_ais_blackout_cannot_prove_continuous_dwell(self):
        points = [
            ais_point("10:00", "BERTH", 1),
            ais_point("12:05", "BERTH", 2),
        ]
        result = reconstruct_port_call(port_id="SANTOS", ais_points=points)
        self.assertNotIn("ATRACADO", [row.state for row in result.events])

    def test_uninterrupted_dwell_still_detected(self):
        points = [
            ais_point("10:00", "ANCHORAGE", 1),
            ais_point("10:15", "ANCHORAGE", 2),
            ais_point("10:35", "ANCHORAGE", 3),
        ]
        result = reconstruct_port_call(port_id="SANTOS", ais_points=points)
        states = [row.state for row in result.events]
        self.assertIn("FUNDEADO", states)
        self.assertIn("AGUARDANDO", states)

    def test_second_clean_dwell_run_is_detected(self):
        points = [
            ais_point("10:00", "ANCHORAGE", 1),
            ais_point("10:05", "SEA", 2),
            ais_point("11:00", "ANCHORAGE", 3),
            ais_point("11:15", "ANCHORAGE", 4),
        ]
        result = reconstruct_port_call(port_id="SANTOS", ais_points=points)
        self.assertIn("FUNDEADO", [row.state for row in result.events])

    def test_matching_imo_at_another_port_is_not_local_arrival(self):
        observations = [AISObservation(
            observed_at="2026-10-20T10:30:00+00:00",
            imo="9000001",
            mmsi="710123456",
            vessel_name="TEST VESSEL",
            port_id="PARANAGUA",
            zone="BERTH",
        )]
        self.assertFalse(match_lineup_call(call(), observations).matched)
        result = reconcile_call(call(), observations)
        self.assertEqual(result.state, "PROGRAMMED")
        self.assertEqual(result.evidence_class, "LINEUP_PROGRAMMED")

    def test_official_operation_from_other_port_rejected(self):
        operation = PortOperation(
            call_id="DUV-001", port_id="PARANAGUA",
            source_id="OFFICIAL_FIXTURE", operation_status="COMPLETED",
        )
        with self.assertRaisesRegex(ValueError, "does not belong"):
            reconcile_call(call(), [], operation)

    def test_official_operation_with_other_call_id_rejected(self):
        operation = PortOperation(
            call_id="DUV-002", port_id="SANTOS",
            source_id="OFFICIAL_FIXTURE", operation_status="COMPLETED",
        )
        with self.assertRaisesRegex(ValueError, "does not belong"):
            reconcile_call(call(), [], operation)

    def test_official_operation_without_provenance_rejected(self):
        operation = PortOperation(
            call_id="DUV-001", port_id="SANTOS",
            source_id=" ", operation_status="COMPLETED",
        )
        with self.assertRaisesRegex(ValueError, "source provenance"):
            reconcile_call(call(), [], operation)

    def test_duplicate_lineup_call_cannot_count_as_two_port_calls(self):
        with self.assertRaisesRegex(ValueError, "duplicate line-up"):
            reconcile_lineup_snapshot([call(), call()], [])

    def test_duplicate_official_operations_do_not_overwrite(self):
        operation = PortOperation(
            call_id="DUV-001", port_id="SANTOS",
            source_id="OFFICIAL_FIXTURE", operation_status="COMPLETED",
        )
        with self.assertRaisesRegex(ValueError, "duplicate official operation"):
            reconcile_lineup_snapshot([call()], [], [operation, operation])

    def test_independent_official_operation_remains_valid(self):
        operation = PortOperation(
            call_id="DUV-001", port_id="SANTOS",
            source_id="OFFICIAL_FIXTURE", operation_status="COMPLETED",
        )
        rows = reconcile_lineup_snapshot([call()], [], [operation])
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0].state, "COMPLETED_REALIZED")
        self.assertEqual(rows[0].evidence_class, "PORT_OPERATION_OBSERVED")


if __name__ == "__main__":
    unittest.main()
