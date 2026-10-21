"""Testes offline de acesso read-only e consulta BigQuery somente dry-run."""
from __future__ import annotations

import subprocess
import sys
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import bigquery_sandbox_dryrun as smoke  # noqa: E402


def report(*, billing="DISABLED", api=True, verified=True, project="nivon-data"):
    return {
        "project_id": project,
        "project_verified_by_api": verified,
        "billing_status": billing,
        "api_inventory_verified": True,
        "apis_of_interest": {"bigquery.googleapis.com": api},
    }


class TestBigqueryPreflight(unittest.TestCase):
    def test_billing_disabled_and_api_enabled_runs_only_dry_run(self):
        calls = []
        def fake(command, **kw):
            calls.append((command, kw))
            return subprocess.CompletedProcess(command, 0, "success", "")
        r = smoke.preflight("nivon-data", report(), runner=fake)
        self.assertTrue(r["dry_run_validated"])
        self.assertEqual(r["next_gate"], "SANDBOX_DRY_RUN_OK_NO_DATA_STORED")
        self.assertEqual(len(calls), 1)
        command, opts = calls[0]
        self.assertEqual(command[0], "bq")
        self.assertIn("--dry_run", command)
        self.assertIn("--maximum_bytes_billed=1073741824", command)
        self.assertIn("--project_id=nivon-data", command)
        self.assertIn("--location=us-central1", command)
        self.assertNotIn("--destination_table", " ".join(command))
        self.assertNotIn("CREATE TABLE", " ".join(command))
        self.assertEqual(opts["timeout"], 30)
        self.assertFalse(r["resources_created"])
        self.assertFalse(r["paid_spending_authorized"])
        self.assertFalse(r["migration_performed"])

    def test_billing_enabled_never_launches_bq(self):
        with mock.patch.object(smoke.subprocess, "run", side_effect=AssertionError("bq launched")):
            r = smoke.preflight("nivon-data", report(billing="ENABLED"))
        self.assertFalse(r["dry_run_validated"])
        self.assertEqual(r["next_gate"], "BILLING_VERIFICATION_OR_REVIEW_REQUIRED")

    def test_billing_unknown_never_launches_bq(self):
        with mock.patch.object(smoke.subprocess, "run", side_effect=AssertionError("bq launched")):
            r = smoke.preflight("nivon-data", report(billing="UNKNOWN_NOT_VERIFIED"))
        self.assertFalse(r["dry_run_validated"])

    def test_api_disabled_never_launches_bq(self):
        with mock.patch.object(smoke.subprocess, "run", side_effect=AssertionError("bq launched")):
            r = smoke.preflight("nivon-data", report(api=False))
        self.assertEqual(r["next_gate"], "BIGQUERY_API_ENABLEMENT_NEEDS_SEPARATE_REVIEW")
        self.assertFalse(r["dry_run_validated"])

    def test_missing_api_result_never_launches_bq(self):
        bad = report()
        bad["apis_of_interest"] = None
        with mock.patch.object(smoke.subprocess, "run", side_effect=AssertionError("bq launched")):
            r = smoke.preflight("nivon-data", bad)
        self.assertFalse(r["dry_run_validated"])

    def test_wrong_project_never_launches_bq(self):
        with mock.patch.object(smoke.subprocess, "run", side_effect=AssertionError("bq launched")):
            r = smoke.preflight("nivon-data", report(project="other"))
        self.assertEqual(r["next_gate"], "PROJECT_VERIFICATION_REQUIRED")

    def test_denied_project_never_launches_bq(self):
        with mock.patch.object(smoke.subprocess, "run", side_effect=AssertionError("bq launched")):
            r = smoke.preflight("nivon-data", report(verified=False))
        self.assertEqual(r["next_gate"], "PROJECT_VERIFICATION_REQUIRED")

    def test_bq_failure_redacts_output_and_does_not_claim_success(self):
        def fake(command, **kw):
            return subprocess.CompletedProcess(command, 1, "private data", "some sensitive error")
        r = smoke.preflight("nivon-data", report(), runner=fake)
        self.assertEqual(r["next_gate"], "BIGQUERY_DRY_RUN_NOT_AVAILABLE")
        self.assertFalse(r["dry_run_validated"])
        self.assertNotIn("private", str(r))
        self.assertNotIn("sensitive", str(r))

    def test_timeouts_never_claim_success(self):
        def fake(command, **kw):
            raise subprocess.TimeoutExpired(command, 30)
        r = smoke.preflight("nivon-data", report(), runner=fake)
        self.assertFalse(r["dry_run_validated"])

    def test_invoking_main_without_check_never_calls_gcp(self):
        with mock.patch.object(smoke.audit_gcp_readonly, "audit", side_effect=AssertionError("audited")):
            with mock.patch("sys.stdout"):
                self.assertEqual(smoke.main([]), 2)


if __name__ == "__main__":
    unittest.main()
