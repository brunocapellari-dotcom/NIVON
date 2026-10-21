"""Regressões GCP: apenas fixtures, sem credenciais/rede ou consultas reais."""
from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
import unittest
from pathlib import Path
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "audit_gcp_readonly.py"
_spec = importlib.util.spec_from_file_location("nivon_audit_gcp_readonly", SCRIPT)
assert _spec is not None and _spec.loader is not None
audit_module = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(audit_module)

PROJECT = ("projects", "describe", "nivon-data", "--format=json")
BILLING = ("billing", "projects", "describe", "nivon-data", "--format=json")
SERVICES = ("services", "list", "--enabled", "--project=nivon-data", "--format=json")
IAM = ("projects", "get-iam-policy", "nivon-data", "--format=json")


def fake_client(billing=False, *, project_valid=True, missing_billing=False, services=None, iam=True):
    records = {
        PROJECT: {"projectId": "nivon-data" if project_valid else "other", "lifecycleState": "ACTIVE"},
        SERVICES: (
            [{"config": {"name": "bigquery.googleapis.com"}},
             {"config": {"name": "storage.googleapis.com"}},
             {"config": {"name": "invalid/untrusted"}}
            ] if services is None else services
        ),
        IAM: {"bindings": [
            {"role": "roles/viewer", "members": ["user:person@private.example"]},
            {"role": "roles/billing.viewer", "members": ["user:person@private.example"]},
        ]} if iam else None,
        BILLING: None if missing_billing else {
            "billingEnabled": billing, "billingAccountName": "billingAccounts/SUPER_PRIVATE_ACCOUNT"
        },
    }
    calls = []

    def fetch(args):
        key = tuple(args)
        calls.append(key)
        return records.get(key)

    return fetch, calls


class ReadOnlyAuditTests(unittest.TestCase):
    def test_offline_check_no_billing_and_sensitive_data_suppressed(self):
        fetch, calls = fake_client()
        result = audit_module.audit("nivon-data", fetch)
        self.assertEqual(result["project_id"], "nivon-data")
        self.assertTrue(result["project_verified_by_api"])
        self.assertEqual(result["billing_status"], "DISABLED")
        self.assertTrue(result["apis_of_interest"]["bigquery.googleapis.com"])
        self.assertTrue(result["apis_of_interest"]["storage.googleapis.com"])
        self.assertFalse(result["apis_of_interest"]["run.googleapis.com"])
        self.assertEqual(result["iam_binding_count"], 2)
        self.assertEqual(len(calls), 4)
        self.assertEqual(
            calls, [PROJECT, BILLING, SERVICES, IAM]
        )
        self.assertFalse(result["deploy_allowed"])
        self.assertFalse(result["paid_spending_authorized"])
        self.assertFalse(result["resources_deployed_verified"])
        report = json.dumps(result)
        self.assertNotIn("person@private.example", report)
        self.assertNotIn("SUPER_PRIVATE_ACCOUNT", report)
        self.assertNotIn("billingAccountName", report)
        self.assertNotIn("members", report)

    def test_billing_active_does_not_grant_authorization(self):
        fetch, _ = fake_client(billing=True)
        result = audit_module.audit("nivon-data", fetch)
        self.assertEqual(result["billing_status"], "ENABLED")
        self.assertEqual(result["next_gate"], "BILLING_ACTIVE_REVIEW_REQUIRED")
        self.assertFalse(result["deploy_allowed"])

    def test_lack_of_billing_permissions_is_unknown_not_false(self):
        fetch, _ = fake_client(missing_billing=True)
        result = audit_module.audit("nivon-data", fetch)
        self.assertEqual(result["billing_status"], "UNKNOWN_NOT_VERIFIED")
        self.assertEqual(result["next_gate"], "CONFIRM_BILLING_ACCESS")
        self.assertFalse(result["deploy_allowed"])

    def test_missing_field_is_unknown(self):
        fetch, _ = fake_client()
        def without_field(args):
            if tuple(args) == BILLING:
                return {}
            return fetch(args)
        result = audit_module.audit("nivon-data", without_field)
        self.assertEqual(result["billing_status"], "UNKNOWN_NOT_VERIFIED")

    def test_wrong_project_never_queries_billing_or_iam(self):
        fetch, calls = fake_client(project_valid=False)
        result = audit_module.audit("nivon-data", fetch)
        self.assertFalse(result["project_verified_by_api"])
        self.assertEqual(result["next_gate"], "CONFIRM_PROJECT_ACCESS")
        self.assertEqual(result["billing_status"], "UNKNOWN_NOT_VERIFIED")
        self.assertEqual(calls, [PROJECT])

    def test_services_access_failure_stays_unknown(self):
        fetch, _ = fake_client(services=None)
        def denied(args):
            if tuple(args) == SERVICES:
                return None
            return fetch(args)
        result = audit_module.audit("nivon-data", denied)
        self.assertIsNone(result["enabled_apis"])
        self.assertIsNone(result["apis_of_interest"])
        self.assertFalse(result["api_inventory_verified"])

    def test_iam_access_failure_does_not_masquerade_as_zero(self):
        fetch, _ = fake_client(iam=False)
        result = audit_module.audit("nivon-data", fetch)
        self.assertFalse(result["iam_audit_verified"])
        self.assertIsNone(result["iam_binding_count"])

    def test_cli_without_check_is_inert(self):
        with mock.patch.object(audit_module, "gcloud_json", side_effect=AssertionError("called")):
            with mock.patch("sys.stdout"):
                self.assertEqual(audit_module.main([]), 2)

    def test_cli_rejects_mismatched_project(self):
        with mock.patch.object(audit_module, "gcloud_json", side_effect=AssertionError("called")):
            with mock.patch("sys.stderr"):
                self.assertEqual(audit_module.main(["--check", "--project", "other-project"]), 2)

    def test_reject_unlisted_gcloud_commands(self):
        with self.assertRaises(ValueError):
            audit_module.gcloud_json(("services", "enable", "bigquery.googleapis.com"))
        with self.assertRaises(ValueError):
            audit_module.gcloud_json(("billing", "projects", "link", "nivon-data"))

    def test_timeouts_hide_raw_stderr(self):
        with mock.patch.object(audit_module.subprocess, "run", side_effect=subprocess.TimeoutExpired("gcloud", 30)):
            result = audit_module.gcloud_json(PROJECT)
        self.assertIsNone(result)


if __name__ == "__main__":
    unittest.main()
