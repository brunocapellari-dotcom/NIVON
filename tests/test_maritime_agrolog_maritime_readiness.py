# Tests adapted from AgroLogMT/tests/test_maritime_readiness.py (2026-10-19).
import unittest

from nivon.maritime.maritime_readiness import (
    MaritimeRuntimeEvidence,
    maritime_capability_gates,
    overall_production_status,
)


class MaritimeReadinessTests(unittest.TestCase):
    def test_empty_evidence_is_production_gated(self):
        result = overall_production_status(MaritimeRuntimeEvidence())
        self.assertEqual(result["status"], "PRODUCTION_GATED")
        self.assertIn("SECURE_RUNTIME", result["core_blockers"])
        self.assertIn("AIS_CAPTURE", result["core_blockers"])

    def test_core_can_pass_without_pretending_advanced_models_are_ready(self):
        evidence = MaritimeRuntimeEvidence(
            security_gate_passed=True,
            main_protected=True,
            wif_verified=True,
            secrets_in_vault=True,
            gateway_private_verified=True,
            ais_real_rows=True,
            ais_five_ports_covered=True,
            lineups_five_ports_fresh=True,
            source_health_operational=True,
        )
        result = overall_production_status(evidence)
        self.assertEqual(result["status"], "PRODUCTION_CORE_READY")
        gates = {row["capability"]: row for row in result["capabilities"]}
        self.assertEqual(gates["AIS_CAPTURE"]["status"], "PASS")
        self.assertEqual(gates["ETA_V1"]["status"], "GATED")
        self.assertEqual(gates["QUEUE_V1"]["status"], "GATED")

    def test_eta_requires_out_of_sample_evidence_and_baseline_win(self):
        evidence = MaritimeRuntimeEvidence(
            geofences_five_ports_validated=True,
            port_call_validation_accuracy=0.97,
            eta_oos_samples=150,
            eta_beats_baseline=False,
        )
        gates = {gate.capability: gate for gate in maritime_capability_gates(evidence)}
        self.assertEqual(gates["ETA_V1"].status, "GATED")
        self.assertIn("beats_declared_baseline", gates["ETA_V1"].blockers)

    def test_queue_requires_30_days_even_if_port_calls_are_good(self):
        evidence = MaritimeRuntimeEvidence(
            geofences_five_ports_validated=True,
            port_call_validation_accuracy=0.99,
            queue_history_days=20,
        )
        gates = {gate.capability: gate for gate in maritime_capability_gates(evidence)}
        self.assertEqual(gates["QUEUE_V1"].status, "GATED")
        self.assertIn("queue_history_at_least_30d", gates["QUEUE_V1"].blockers)


if __name__ == "__main__":
    unittest.main()
