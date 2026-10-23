"""Testes de cadeia de artefatos locais; não requer dependências instaladas."""
from __future__ import annotations

import base64
import hashlib
import io
import json
import tempfile
import unittest
import zipfile
from datetime import datetime, timezone
from pathlib import Path

from nivon.auditoria_artefatos_pacotes import verificar_cadeia
from nivon.auditoria_evidencias_pacotes import ErroEvidencia


class CadeiaPacotesTests(unittest.TestCase):
    def setUp(self):
        self.ctx = tempfile.TemporaryDirectory()
        self.addCleanup(self.ctx.cleanup)
        self.root = Path(self.ctx.name)
        self.project = (
            '[project]\nname = "nivon"\nrequires-python = ">=3.11"\n'
            'dependencies = []\n'
            '[project.optional-dependencies]\n'
            'ivo-query = ["duckdb>=1,<2"]\n'
        )
        raw = io.BytesIO()
        files = {
            "duckdb-1.2.3.dist-info/METADATA":
                b"Metadata-Version: 2.1\nName: duckdb\nVersion: 1.2.3\n",
            "duckdb-1.2.3.dist-info/WHEEL":
                b"Wheel-Version: 1.0\n",
        }
        record = ""
        for name, data in files.items():
            digest = base64.urlsafe_b64encode(hashlib.sha256(data).digest()).decode().rstrip("=")
            record += f"{name},sha256={digest},{len(data)}\n"
        record += "duckdb-1.2.3.dist-info/RECORD,,\n"
        with zipfile.ZipFile(raw, "w", compression=zipfile.ZIP_DEFLATED) as z:
            for name, data in files.items():
                z.writestr(name, data)
            z.writestr("duckdb-1.2.3.dist-info/RECORD", record.encode())
        self.wheel = self.root / "duckdb-1.2.3-py3-none-any.whl"
        self.wheel.write_bytes(raw.getvalue())
        self.lock = "duckdb==1.2.3 --hash=sha256:" + hashlib.sha256(raw.getvalue()).hexdigest() + "\n"
        self.report_data = {
            "dependencies": [{"name": "duckdb", "version": "1.2.3", "vulns": []}],
            "fixes": [],
        }
        self.report = json.dumps(self.report_data)
        self.meta = self.make_meta()
        self.now = datetime(2026, 10, 21, 12, 10, tzinfo=timezone.utc)

    def make_meta(self):
        digest = lambda s: hashlib.sha256(s.encode()).hexdigest()
        return {
            "pyproject_sha256": digest(self.project),
            "lock_sha256": digest(self.lock),
            "report_sha256": digest(self.report),
            "generated_at": "2026-10-21T12:00:00Z",
            "tool": "pip-audit", "service": "pypi", "exit_code": 0,
            "extras": ["ivo-query"],
        }

    def run_chain(self):
        return verificar_cadeia(self.project, self.lock, self.report, self.meta,
                               self.root, agora=self.now)

    def test_coherent_chain_still_blocks_release(self):
        res = self.run_chain()
        self.assertEqual(res["wheels_hash_verified"], 1)
        self.assertEqual(res["direct_packages_checked"], 1)
        self.assertTrue(res["lock_report_coherent"])
        self.assertTrue(res["local_wheel_hashes_match_declared_lock"])
        self.assertTrue(res["wheel_record_integrity_verified"])
        self.assertFalse(res["approved_for_production"])
        self.assertEqual(res["license_distributions_requiring_review"], 1)
        self.assertEqual(res["license_files_declared"], 0)
        self.assertTrue(res["license_files_integrity_checked"])
        self.assertFalse(res["legal_license_review_completed"])
        self.assertFalse(res["spdx_identifiers_validated"])
        self.assertFalse(res["transitive_closure_proven"])
        self.assertFalse(res["audit_executor_authenticated"])
        self.assertFalse(res["approved_for_production"])

    def test_original_lock_tampering_blocked(self):
        self.lock = self.lock.replace("duckdb==1.2.3", "duckdb==1.2.4")
        with self.assertRaisesRegex(ErroEvidencia, "hash de artefato divergente"):
            self.run_chain()

    def test_artifact_modified_after_lock_metadata_creation(self):
        self.wheel.write_bytes(self.wheel.read_bytes() + b"tamper")
        with self.assertRaisesRegex(ErroEvidencia, "SHA256"):
            self.run_chain()

    def test_report_incomplete_even_with_good_wheel(self):
        self.report_data["dependencies"] = []
        self.report = json.dumps(self.report_data)
        self.meta = self.make_meta()
        with self.assertRaisesRegex(ErroEvidencia, "não coincide"):
            self.run_chain()

    def test_report_claiming_vulnerability_is_recorded_not_ignored(self):
        self.report_data["dependencies"][0]["vulns"] = [
            {"id": "PYSEC-SYNTHETIC-1", "fix_versions": []},
        ]
        self.report = json.dumps(self.report_data)
        self.meta = self.make_meta()
        self.meta["exit_code"] = 1
        res = self.run_chain()
        self.assertEqual(res["reported_vulnerabilities"], 1)
        self.assertFalse(res["reported_no_vulnerabilities"])
        self.assertFalse(res["approved_for_install"])

    def test_stale_report_is_rejected_before_wheel_acceptance(self):
        self.meta["generated_at"] = "2026-10-19T12:00:00Z"
        with self.assertRaisesRegex(ErroEvidencia, "antiga"):
            self.run_chain()

    def test_bad_wheel_identity_even_with_matching_hash_rejected(self):
        self.wheel.rename(self.root / "different-1.2.3-py3-none-any.whl")
        with self.assertRaisesRegex(ErroEvidencia, "wheel extra"):
            self.run_chain()

    def test_missing_wheel_never_claims_integrity(self):
        self.wheel.unlink()
        with self.assertRaisesRegex(ErroEvidencia, "vazio"):
            self.run_chain()


if __name__ == "__main__":
    unittest.main()
