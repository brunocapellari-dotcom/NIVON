# Reused from AgroLogMT/tests/test_maritime_port_state.py; verify provenance/license before commercial release.
import unittest

from nivon.maritime.maritime_port_state import (
    MaritimePhysicalState,
    StateEvidence,
    canonical_state_order,
    validate_state_evidence,
    validate_transition,
)


class MaritimePortStateTests(unittest.TestCase):
    def test_canonical_state_order_matches_operational_model(self):
        self.assertEqual(canonical_state_order(), [
            "PROGRAMADO", "EM_VIAGEM", "APROXIMACAO", "AREA_PORTUARIA",
            "FUNDEADO", "AGUARDANDO", "MANOBRA", "ATRACADO", "OPERANDO",
            "CONCLUIDO", "DESATRACADO", "SAIU",
        ])

    def test_single_ais_message_cannot_confirm_physical_state(self):
        evidence = [StateEvidence(
            source_id="aisstream",
            evidence_class="OBSERVADO",
            observed_at="2026-09-14T12:00:00+00:00",
            signal_type="AIS_POSITION",
            independent_message_count=1,
        )]
        with self.assertRaises(ValueError):
            validate_state_evidence(MaritimePhysicalState.FUNDEADO, evidence)

    def test_two_ais_messages_can_support_non_official_physical_state(self):
        evidence = [StateEvidence(
            source_id="aisstream",
            evidence_class="OBSERVADO",
            observed_at="2026-09-14T12:00:00+00:00",
            signal_type="AIS_POSITION",
            independent_message_count=2,
        )]
        validate_state_evidence(MaritimePhysicalState.APROXIMACAO, evidence)

    def test_operating_requires_official_operational_evidence(self):
        ais = [StateEvidence(
            source_id="aisstream",
            evidence_class="OBSERVADO",
            observed_at="2026-09-14T12:00:00+00:00",
            signal_type="AIS_POSITION",
            independent_message_count=3,
        )]
        with self.assertRaises(ValueError):
            validate_state_evidence(MaritimePhysicalState.OPERANDO, ais)

        official = ais + [StateEvidence(
            source_id="port_authority",
            evidence_class="OBSERVADO",
            observed_at="2026-09-14T12:02:00+00:00",
            signal_type="PORT_OPERATION",
            official_operational=True,
        )]
        validate_state_evidence(MaritimePhysicalState.OPERANDO, official)

    def test_transition_regression_is_blocked(self):
        with self.assertRaises(ValueError):
            validate_transition("ATRACADO", "APROXIMACAO")


if __name__ == "__main__":
    unittest.main()
