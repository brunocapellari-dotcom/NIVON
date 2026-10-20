"""Prevent false port operations when signals belong to another port call.

Offline and synthetic only. This module tests the public reconstruction contract;
a verified flag is an assertion from a trusted upstream adapter, not a license.
"""
import unittest

from nivon.maritime.port_call_engine import (
    AisStatePoint, OfficialPortSignal, reconstruct_port_call,
)

PORT = "SANTOS"
CALL = "SANTOS:APS:DUV-001"
STAMP = "2026-10-20T14:00:00+00:00"


def point(minute, idx):
    return AisStatePoint(
        observed_at=f"2026-10-20T13:{minute:02d}:00+00:00",
        mmsi="710123456",
        port_id=PORT,
        zone="BERTH",
        quality_status="CONFIRMED_SEQUENCE",
        corroborated=True,
        observation_id=f"test-ais-{idx}",
    )


def signal(**kwargs):
    fields = dict(
        observed_at=STAMP,
        state="CONCLUIDO",
        source_id="OFFICIAL_SYNTHETIC",
        official_operational=True,
        port_id=PORT,
        call_id=CALL,
    )
    fields.update(kwargs)
    return OfficialPortSignal(**fields)


def run_event(event, *, target_call=CALL, port_id=PORT):
    return reconstruct_port_call(
        port_id=port_id,
        call_id=target_call,
        ais_points=(point(10, 1), point(20, 2)),
        official_signals=(event,),
    )


class OfficialSignalScopeTests(unittest.TestCase):
    def test_explicit_same_call_official_event_is_allowed(self):
        result = run_event(signal())
        events = [event for event in result.events if event.state == "CONCLUIDO"]
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0].source_kind, "PORT_OPERATION_OFFICIAL")
        self.assertIn("call:" + CALL, events[0].evidence_refs)
        self.assertIn("port:" + PORT, events[0].evidence_refs)

    def test_second_visit_of_same_vessel_cannot_complete_first(self):
        with self.assertRaisesRegex(ValueError, "call_id mismatch"):
            run_event(signal(call_id="SANTOS:APS:DUV-002"))

    def test_event_from_other_port_cannot_complete_visit(self):
        with self.assertRaisesRegex(ValueError, "port_id mismatch"):
            run_event(signal(port_id="PARANAGUA"))

    def test_missing_target_call_id_rejected(self):
        with self.assertRaisesRegex(ValueError, "requires target call_id"):
            run_event(signal(), target_call=None)

    def test_missing_official_call_id_rejected(self):
        with self.assertRaisesRegex(ValueError, "call_id mismatch"):
            run_event(signal(call_id=None))

    def test_missing_official_port_id_rejected(self):
        with self.assertRaisesRegex(ValueError, "port_id mismatch"):
            run_event(signal(port_id=None))

    def test_missing_official_source_rejected(self):
        with self.assertRaisesRegex(ValueError, "requires source_id"):
            run_event(signal(source_id=" "))

    def test_default_signal_is_not_official(self):
        row = OfficialPortSignal(STAMP, "CONCLUIDO", "UNVERIFIED_DOCUMENT", port_id=PORT, call_id=CALL)
        result = run_event(row)
        self.assertEqual(result.current_state, "ATRACADO")
        self.assertIn("nonofficial_port_signal_excluded", result.flags)
        self.assertNotIn("CONCLUIDO", [item.state for item in result.events])

    def test_nonofficial_claim_cannot_override_port_call_identity(self):
        result = run_event(signal(official_operational=False, port_id="PARANAGUA", call_id="DIFFERENT"))
        self.assertNotIn("CONCLUIDO", [item.state for item in result.events])

    def test_missing_identity_official_event_fails_without_ais(self):
        with self.assertRaisesRegex(ValueError, "requires target call_id"):
            reconstruct_port_call(port_id=PORT, ais_points=(), official_signals=(signal(),))

    def test_nonofficial_signal_without_ais_remains_not_confirmed(self):
        result = reconstruct_port_call(
            port_id=PORT, ais_points=(),
            official_signals=(signal(official_operational=False),),
        )
        self.assertEqual(result.status, "DATA_GATED")
        self.assertNotIn("CONCLUIDO", [event.state for event in result.events])


if __name__ == "__main__":
    unittest.main()
