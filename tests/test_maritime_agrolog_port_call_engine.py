# Reused from AgroLogMT/tests/test_port_call_engine.py; verify provenance/license before commercial release.
import unittest

from nivon.maritime.port_call_engine import AisStatePoint, OfficialPortSignal, reconstruct_port_call


def point(at, zone, idx, *, port="SANTOS", corroborated=True, quality="CONFIRMED_SEQUENCE"):
    return AisStatePoint(
        observed_at=at,
        mmsi="710123456",
        port_id=port,
        zone=zone,
        quality_status=quality,
        corroborated=corroborated,
        observation_id=f"obs-{idx}",
    )


class PortCallEngineTests(unittest.TestCase):
    def test_single_position_never_confirms_port_state(self):
        result = reconstruct_port_call(
            port_id="SANTOS",
            ais_points=[point("2026-09-15T10:00:00+00:00", "ANCHORAGE", 1, corroborated=False, quality="UNCONFIRMED_SINGLE")],
            scheduled_at="2026-09-15T08:00:00+00:00",
        )
        self.assertEqual(result.current_state, "PROGRAMADO")
        self.assertEqual([event.state for event in result.events], ["PROGRAMADO"])

    def test_quarantined_position_is_excluded(self):
        result = reconstruct_port_call(
            port_id="SANTOS",
            ais_points=[point("2026-09-15T10:00:00+00:00", "BERTH", 1, quality="QUARANTINE")],
        )
        self.assertEqual(result.current_state, "PROGRAMADO")
        self.assertIn("quarantined_ais_excluded", result.flags)

    def test_anchor_wait_berth_sequence_reconstructs_waiting(self):
        points = [
            point("2026-09-15T09:00:00+00:00", "APPROACH", 1),
            point("2026-09-15T09:02:00+00:00", "APPROACH", 2),
            point("2026-09-15T10:00:00+00:00", "ANCHORAGE", 3),
            point("2026-09-15T10:15:00+00:00", "ANCHORAGE", 4),
            point("2026-09-15T10:35:00+00:00", "ANCHORAGE", 5),
            point("2026-09-15T12:00:00+00:00", "CHANNEL", 6),
            point("2026-09-15T12:02:00+00:00", "CHANNEL", 7),
            point("2026-09-15T12:20:00+00:00", "BERTH", 8),
            point("2026-09-15T12:30:00+00:00", "BERTH", 9),
        ]
        result = reconstruct_port_call(port_id="SANTOS", ais_points=points)
        states = [event.state for event in result.events]
        self.assertIn("APROXIMACAO", states)
        self.assertIn("FUNDEADO", states)
        self.assertIn("AGUARDANDO", states)
        self.assertIn("MANOBRA", states)
        self.assertIn("ATRACADO", states)
        self.assertEqual(result.current_state, "ATRACADO")
        self.assertGreater(result.waiting_hours or 0, 2.0)

    def test_operating_and_completed_require_official_signal(self):
        points = [
            point("2026-09-15T12:20:00+00:00", "BERTH", 1),
            point("2026-09-15T12:30:00+00:00", "BERTH", 2),
        ]
        no_official = reconstruct_port_call(port_id="SANTOS", ais_points=points)
        self.assertEqual(no_official.current_state, "ATRACADO")

        official = reconstruct_port_call(
            port_id="SANTOS",
            call_id="SANTOS:DUV:123",
            ais_points=points,
            official_signals=[
                OfficialPortSignal("2026-09-15T13:00:00+00:00", "OPERANDO", "aps",
                                   port_id="SANTOS", call_id="SANTOS:DUV:123", official_operational=True),
                OfficialPortSignal("2026-09-15T18:00:00+00:00", "CONCLUIDO", "aps",
                                   port_id="SANTOS", call_id="SANTOS:DUV:123", official_operational=True),
            ],
        )
        self.assertEqual(official.current_state, "CONCLUIDO")
        self.assertTrue(all(
            event.source_kind == "PORT_OPERATION_OFFICIAL"
            for event in official.events if event.state in {"OPERANDO", "CONCLUIDO"}
        ))

    def test_other_port_does_not_contaminate_call(self):
        result = reconstruct_port_call(
            port_id="SANTOS",
            ais_points=[
                point("2026-09-15T10:00:00+00:00", "BERTH", 1, port="PARANAGUA"),
                point("2026-09-15T10:10:00+00:00", "BERTH", 2, port="PARANAGUA"),
            ],
        )
        self.assertEqual(result.current_state, "PROGRAMADO")
        self.assertIn("other_port_ais_excluded", result.flags)


if __name__ == "__main__":
    unittest.main()
