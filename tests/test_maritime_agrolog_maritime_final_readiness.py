# Tests adapted from AgroLogMT/tests/test_maritime_final_readiness.py (2026-10-19).
import json
import unittest
from pathlib import Path

from nivon.maritime.maritime_final_readiness import (
    GateEvidence,
    REQUIRED_FINAL_GATES,
    evaluate_final_readiness,
)


class MaritimeFinalReadinessTests(unittest.TestCase):
    def _evidence(self, gate: str, passed: bool = True) -> GateEvidence:
        return GateEvidence(
            gate=gate,
            passed=passed,
            evidence_ref=f"evidence://{gate}",
            measured_at="2026-09-15T12:00:00+00:00",
        )

    def test_contract_and_runtime_gate_lists_are_identical(self):
        contract = json.loads(
            Path("contracts/maritime_final_acceptance.v1.json").read_text(encoding="utf-8")
        )
        self.assertEqual(tuple(contract["final_gates"]), REQUIRED_FINAL_GATES)
        self.assertEqual(contract["release_policy"], "ALL_OR_NOTHING")
        self.assertFalse(contract["partial_module_release_allowed"])

    def test_missing_single_gate_blocks_entire_product(self):
        rows = [self._evidence(g) for g in REQUIRED_FINAL_GATES[:-1]]
        result = evaluate_final_readiness(rows)
        self.assertEqual(result.status, "BLOCKED")
        self.assertFalse(result.final_ready)
        self.assertEqual(result.blocked_gates, (REQUIRED_FINAL_GATES[-1],))

    def test_failed_single_gate_blocks_entire_product(self):
        rows = [self._evidence(g, passed=(g != "security_gate")) for g in REQUIRED_FINAL_GATES]
        result = evaluate_final_readiness(rows)
        self.assertEqual(result.status, "BLOCKED")
        self.assertIn("security_gate", result.blocked_gates)

    def test_only_all_gates_can_produce_final_ready(self):
        rows = [self._evidence(g) for g in REQUIRED_FINAL_GATES]
        result = evaluate_final_readiness(rows)
        self.assertEqual(result.status, "FINAL_READY")
        self.assertTrue(result.final_ready)
        self.assertEqual(result.blocked_gates, ())

    def test_duplicate_evidence_is_rejected(self):
        row = self._evidence("repository_full_tests")
        with self.assertRaises(ValueError):
            evaluate_final_readiness([row, row])

    def test_unknown_gate_is_rejected(self):
        with self.assertRaises(ValueError):
            evaluate_final_readiness([self._evidence("module_green")])


if __name__ == "__main__":
    unittest.main()
