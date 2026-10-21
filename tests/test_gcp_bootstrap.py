"""Testes offline do script de criacao segura do projeto GCP."""
from __future__ import annotations

import shutil
import subprocess
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "bootstrap_gcp_project.sh"
GUIDE = ROOT / "docs" / "BOOTSTRAP_GCP_PROJETO_NIVON.md"


class GcpBootstrapTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.source = SCRIPT.read_text(encoding="utf-8")
        cls.guide = GUIDE.read_text(encoding="utf-8")

    def test_script_bash_syntax(self):
        if shutil.which("bash") is None:
            self.skipTest("bash indisponivel")
        result = subprocess.run(["bash", "-n", str(SCRIPT)], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_no_paid_services_or_secrets(self):
        text = self.source
        for forbidden in (
            "gcloud billing projects link", "gcloud services enable",
            "gcloud storage buckets create", "bq mk", "terraform apply",
            "gcloud run deploy", "gcloud auth activate-service-account",
            "gcloud iam service-accounts keys create",
        ):
            self.assertNotIn(forbidden, text)
        self.assertIn("--no-enable-cloud-apis", text)
        self.assertIn('MODE" == "--create"', text)
        self.assertIn('CONFIRMATION" != "$PROJECT_ID"', text)
        self.assertIn('BILLING_ENABLED" != "false"', text)

    def test_default_invocation_is_not_mutating(self):
        if shutil.which("bash") is None:
            self.skipTest("bash indisponivel")
        run = subprocess.run(["bash", str(SCRIPT)], capture_output=True, text=True)
        self.assertEqual(run.returncode, 2)
        self.assertIn("--check", run.stdout)

    def test_guards_and_instructions(self):
        self.assertIn("brunocapellari-org", self.guide)
        self.assertIn("não vincular faturamento", self.guide)
        self.assertIn("60 dias", self.guide)
        self.assertIn("bash scripts/bootstrap_gcp_project.sh --check nivon-data", self.guide)
        self.assertIn("Neon", self.guide)
        self.assertIn("não usar esse modo no projeto existente", self.guide)


if __name__ == "__main__":
    unittest.main()
