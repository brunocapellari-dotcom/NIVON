"""Testes de evidências pip-audit, com dados estritamente sintéticos e sem rede."""
from __future__ import annotations

import copy
import hashlib
import json
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from nivon.auditoria_evidencias_pacotes import ErroEvidencia, avaliar, _arquivo


class EvidenciaPacotesTests(unittest.TestCase):
    def setUp(self):
        self.pyproject = (
            '[project]\nname="nivon"\nrequires-python=">=3.11"\n'
            'dependencies = []\n[project.optional-dependencies]\n'
            'ivo-query = ["duckdb>=1,<2"]\n'
            'ivo-ml = ["pandas>=2.2,<3", "mlforecast>=1,<2"]\n'
        )
        self.lock = (
            "duckdb==1.2.0 --hash=sha256:" + "a" * 64 + "\n"
            "pandas==2.2.3 --hash=sha256:" + "b" * 64 + "\n"
            "mlforecast==1.0.1 --hash=sha256:" + "c" * 64 + "\n"
            "numpy==2.1.0 --hash=sha256:" + "d" * 64 + "\n"
        )
        self.report = {"dependencies": [
            {"name": name, "version": version, "vulns": []}
            for name, version in [("duckdb", "1.2.0"), ("pandas", "2.2.3"),
                                  ("mlforecast", "1.0.1"), ("numpy", "2.1.0")]
        ], "fixes": []}
        self.at = datetime(2026, 10, 21, 12, 0, tzinfo=timezone.utc)
        self.meta = self.metadata()

    def metadata(self):
        return {
            "pyproject_sha256": hashlib.sha256(self.pyproject.encode()).hexdigest(),
            "lock_sha256": hashlib.sha256(self.lock.encode()).hexdigest(),
            "report_sha256": hashlib.sha256(json.dumps(self.report).encode()).hexdigest(),
            "generated_at": "2026-10-21T11:00:00Z",
            "tool": "pip-audit", "service": "pypi", "exit_code": 0,
            "extras": ["ivo-ml", "ivo-query"],
        }

    def run_eval(self):
        return avaliar(self.pyproject, self.lock, json.dumps(self.report), self.meta, agora=self.at)

    def test_coherent_does_not_certify_security(self):
        result = self.run_eval()
        self.assertEqual(result["locked_packages"], 4)
        self.assertEqual(result["direct_packages_covered"], 3)
        self.assertTrue(result["reported_no_vulnerabilities"])
        self.assertFalse(result["transitive_dependency_closure_verified"])
        self.assertFalse(result["hashes_downloaded_or_verified"])
        self.assertFalse(result["audit_origin_authenticated"])
        self.assertFalse(result["approved_for_production"])
        self.assertTrue(result["release_gate"].startswith("BLOCKED_"))

    def test_transitive_package_cannot_disappear_from_report(self):
        self.report["dependencies"].pop()
        self.meta = self.metadata()
        with self.assertRaisesRegex(ErroEvidencia, "não coincide"):
            self.run_eval()

    def test_direct_package_must_be_locked(self):
        self.lock = self.lock.replace("duckdb==1.2.0 --hash=sha256:" + "a" * 64 + "\n", "")
        self.meta = self.metadata()
        with self.assertRaisesRegex(ErroEvidencia, "direta ausente"):
            self.run_eval()

    def test_direct_range_mismatch(self):
        self.lock = self.lock.replace("duckdb==1.2.0", "duckdb==2.1.0")
        self.meta = self.metadata()
        with self.assertRaisesRegex(ErroEvidencia, "viola"):
            self.run_eval()

    def test_audit_version_mismatch(self):
        self.report["dependencies"][0]["version"] = "1.1.0"
        self.meta = self.metadata()
        with self.assertRaisesRegex(ErroEvidencia, "diverge"):
            self.run_eval()

    def test_vulnerability_never_marks_release_safe(self):
        self.report["dependencies"][1]["vulns"] = [{"id": "PYSEC-SYNTHETIC-1", "fix_versions": []}]
        self.meta = self.metadata()
        self.meta["exit_code"] = 1
        result = self.run_eval()
        self.assertEqual(result["vulnerabilities_reported"], 1)
        self.assertFalse(result["reported_no_vulnerabilities"])
        self.assertFalse(result["approved_for_production"])

    def test_bad_exit_code_rejected(self):
        self.meta["exit_code"] = 1
        with self.assertRaisesRegex(ErroEvidencia, "exit code"):
            self.run_eval()

    def test_skipped_package_rejected(self):
        self.report["dependencies"][0] = {"name": "duckdb", "skip_reason": "fixture"}
        self.meta = self.metadata()
        with self.assertRaisesRegex(ErroEvidencia, "ignorado"):
            self.run_eval()

    def test_missing_vulns_array_rejected(self):
        del self.report["dependencies"][0]["vulns"]
        self.meta = self.metadata()
        with self.assertRaisesRegex(ErroEvidencia, "não declaradas"):
            self.run_eval()

    def test_forged_hash_rejected(self):
        self.meta["lock_sha256"] = "0" * 64
        with self.assertRaisesRegex(ErroEvidencia, "divergente"):
            self.run_eval()

    def test_duplicate_report_json_keys_rejected(self):
        text = '{"dependencies":[],"dependencies":[],"fixes":[]}'
        meta = self.metadata()
        meta["report_sha256"] = hashlib.sha256(text.encode()).hexdigest()
        with self.assertRaisesRegex(ErroEvidencia, "duplicada"):
            avaliar(self.pyproject, self.lock, text, meta, agora=self.at)

    def test_stale_and_future_attestation_rejected(self):
        for value in ["2026-10-20T10:00:00Z", "2026-10-22T01:00:00Z"]:
            self.meta["generated_at"] = value
            with self.subTest(value=value), self.assertRaisesRegex(ErroEvidencia, "antiga|futura"):
                self.run_eval()

    def test_unauthenticated_service_rejected(self):
        self.meta["service"] = "arbitrary-host"
        with self.assertRaisesRegex(ErroEvidencia, "não declarado"):
            self.run_eval()

    def test_ambiguous_extras_rejected(self):
        for extras in [[], ["ivo-query", "ivo-query"], ["missing"]]:
            self.meta["extras"] = extras
            with self.subTest(extras=extras), self.assertRaises(ErroEvidencia):
                self.run_eval()

    def test_duplicates_and_directives_in_lock_rejected(self):
        cases = [
            self.lock + "duckdb==1.2.0 --hash=sha256:" + "a" * 64,
            self.lock + "--extra-index-url https://fake.invalid",
            self.lock.replace("--hash=sha256:" + "a" * 64, ""),
            self.lock + "evil==1.0 --hash=sha256:" + "a" * 64,
        ]
        original = self.lock
        for value in cases:
            self.lock = value
            self.meta = self.metadata()
            with self.subTest(value=value[-50:]), self.assertRaises(ErroEvidencia):
                self.run_eval()
            self.lock = original
            self.meta = self.metadata()

    def test_symlinks_for_evidence_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            original = root / "report.json"
            original.write_text(json.dumps(self.report), encoding="utf-8")
            link = root / "symlink.json"
            link.symlink_to(original)
            with self.assertRaises(ErroEvidencia):
                _arquivo(link, 2000)

    def test_no_real_packages_installed_by_this_test(self):
        result = self.run_eval()
        self.assertFalse(result["real_vulnerability_scan_performed_by_this_module"])
        self.assertFalse(result["installed_package_tests_performed"])


if __name__ == "__main__":
    unittest.main()
