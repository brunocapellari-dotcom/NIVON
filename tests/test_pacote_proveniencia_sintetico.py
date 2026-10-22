"""Ensaio de origem assinado: somente bytes sintéticos, sem rede/deps."""
from __future__ import annotations

import hashlib
import io
import json
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch

from nivon.auditoria_evidencias_pacotes import ErroEvidencia
from nivon.pacote_proveniencia_sintetico import (
    REPO, SCHEMA, criar_pacote, main, verificar_pacote,
)


SHA = "a" * 40
RUN = 89123
PROJECT = b'[project]\nname="nivon"\nversion="0.1.0"\n'


def adulterar(original: bytes, *, new_manifest=None, new_project=None,
              extra=None, omit=None):
    stream = io.BytesIO()
    with zipfile.ZipFile(io.BytesIO(original)) as z:
        files = {k: z.read(k) for k in z.namelist() if k != omit}
    if new_manifest is not None:
        files["manifesto.json"] = (
            json.dumps(new_manifest, ensure_ascii=False).encode("utf-8"))
    if new_project is not None:
        files["pyproject.toml"] = new_project
    if extra is not None:
        files[extra] = b"unlisted synthetic data"
    with zipfile.ZipFile(stream, "w") as z:
        for name, raw in files.items():
            z.writestr(name, raw)
    return stream.getvalue()


class PacoteProvenienciaSinteticoTests(unittest.TestCase):
    def setUp(self):
        self.blob = criar_pacote(PROJECT, repo=REPO, source_sha=SHA, run_id=RUN)

    def valid(self, raw=None):
        return verificar_pacote(
            self.blob if raw is None else raw,
            repo=REPO, source_sha=SHA, run_id=RUN)

    def test_deterministic_fixed_inputs_and_local_zip_hash(self):
        same = criar_pacote(PROJECT, repo=REPO, source_sha=SHA, run_id=RUN)
        self.assertEqual(self.blob, same)
        res = self.valid()
        self.assertEqual(res["zip_sha256"], hashlib.sha256(self.blob).hexdigest())
        self.assertEqual(res["zip_bytes"], len(self.blob))
        self.assertTrue(res["synthetic_content_consistent"])
        self.assertFalse(res["github_signature_verified"])
        self.assertFalse(res["external_packages_verified"])
        self.assertFalse(res["approved_for_production"])

    def test_manifest_never_claims_real_dependency_scan(self):
        with zipfile.ZipFile(io.BytesIO(self.blob)) as z:
            manifest = json.loads(z.read("manifesto.json"))
            self.assertEqual(z.namelist(), ["manifesto.json", "pyproject.toml"])
        self.assertEqual(manifest["schema"], SCHEMA)
        self.assertEqual(manifest["evidence_type"],
                         "SYNTHETIC_WORKFLOW_TEST_NOT_DEPENDENCY_EVIDENCE")
        for k in ("third_party_downloads_performed", "pip_install_performed",
                  "dependency_resolution_performed", "real_vulnerability_scan_performed",
                  "third_party_license_review_performed", "approved_for_install",
                  "approved_for_production"):
            self.assertIs(manifest[k], False)

    def test_modified_project_bytes_rejected_even_with_valid_outer_zip(self):
        with self.assertRaisesRegex(ErroEvidencia, "não coincide"):
            self.valid(adulterar(self.blob, new_project=PROJECT + b"# change\n"))

    def test_added_member_rejected(self):
        with self.assertRaisesRegex(ErroEvidencia, "faltantes/extras"):
            self.valid(adulterar(self.blob, extra="extra.txt"))

    def test_missing_member_rejected(self):
        with self.assertRaisesRegex(ErroEvidencia, "faltantes/extras"):
            self.valid(adulterar(self.blob, omit="pyproject.toml"))

    def test_claimed_approval_rejected(self):
        with zipfile.ZipFile(io.BytesIO(self.blob)) as z:
            manifest = json.loads(z.read("manifesto.json"))
        manifest["approved_for_production"] = True
        with self.assertRaisesRegex(ErroEvidencia, "falsa aprovação"):
            self.valid(adulterar(self.blob, new_manifest=manifest))

    def test_claimed_download_rejected(self):
        with zipfile.ZipFile(io.BytesIO(self.blob)) as z:
            manifest = json.loads(z.read("manifesto.json"))
        manifest["third_party_downloads_performed"] = True
        with self.assertRaisesRegex(ErroEvidencia, "falsa aprovação"):
            self.valid(adulterar(self.blob, new_manifest=manifest))

    def test_claimed_release_gate_rejected(self):
        with zipfile.ZipFile(io.BytesIO(self.blob)) as z:
            manifest = json.loads(z.read("manifesto.json"))
        manifest["release_gate"] = "APPROVED"
        with self.assertRaisesRegex(ErroEvidencia, "gate de liberação"):
            self.valid(adulterar(self.blob, new_manifest=manifest))

    def test_wrong_commit_not_accepted(self):
        with self.assertRaisesRegex(ErroEvidencia, "não coincide"):
            verificar_pacote(self.blob, repo=REPO, source_sha="b"*40, run_id=RUN)

    def test_wrong_run_not_accepted(self):
        with self.assertRaisesRegex(ErroEvidencia, "não coincide"):
            verificar_pacote(self.blob, repo=REPO, source_sha=SHA, run_id=RUN+1)

    def test_wrong_repository_not_accepted(self):
        with self.assertRaisesRegex(ErroEvidencia, "identificadores"):
            verificar_pacote(self.blob, repo="unauthorized/repo", source_sha=SHA, run_id=RUN)

    def test_bad_binary_rejected(self):
        with self.assertRaisesRegex(ErroEvidencia, "ZIP"):
            self.valid(b"not zip")

    def test_bad_utf8_pyproject_rejected(self):
        with self.assertRaisesRegex(ErroEvidencia, "UTF-8"):
            criar_pacote(b"\xff", repo=REPO, source_sha=SHA, run_id=RUN)

    def test_missing_project_rejected(self):
        with self.assertRaisesRegex(ErroEvidencia, "ausente"):
            criar_pacote(b"", repo=REPO, source_sha=SHA, run_id=RUN)

    def test_too_large_pyproject_rejected(self):
        with self.assertRaisesRegex(ErroEvidencia, "excessivo"):
            criar_pacote(b"a"*80001, repo=REPO, source_sha=SHA, run_id=RUN)

    def test_invalid_sha_rejected(self):
        with self.assertRaisesRegex(ErroEvidencia, "identificadores"):
            criar_pacote(PROJECT, repo=REPO, source_sha="x"*40, run_id=RUN)

    def test_boolean_run_id_rejected(self):
        with self.assertRaisesRegex(ErroEvidencia, "identificadores"):
            criar_pacote(PROJECT, repo=REPO, source_sha=SHA, run_id=True)

    def test_cli_synthetic_producer_creates_file_without_install(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "pyproject.toml"
            source.write_bytes(PROJECT)
            dest = root / "fixture.zip"
            args = ["program", "--pyproject", str(source), "--output", str(dest),
                    "--repository", REPO, "--source-sha", SHA, "--run-id", str(RUN)]
            with patch.object(sys, "argv", args):
                main()
            self.assertTrue(dest.is_file())
            self.valid(dest.read_bytes())

    def test_cli_will_not_overwrite_existing_zip(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "pyproject.toml"
            source.write_bytes(PROJECT)
            dest = root / "fixture.zip"
            dest.write_bytes(b"preserve-me")
            args = ["program", "--pyproject", str(source), "--output", str(dest),
                    "--repository", REPO, "--source-sha", SHA, "--run-id", str(RUN)]
            with patch.object(sys, "argv", args), self.assertRaises(SystemExit):
                main()
            self.assertEqual(dest.read_bytes(), b"preserve-me")

    def test_workflow_manual_main_only_and_actions_pinned(self):
        wf = (Path(__file__).resolve().parents[1] /
              ".github/workflows/auditoria_pacotes.yml").read_text()
        self.assertIn("workflow_dispatch:", wf)
        self.assertIn("github.ref == 'refs/heads/main'", wf)
        self.assertIn("permissions: {}", wf)
        self.assertIn("id-token: write", wf)
        self.assertIn("attestations: write", wf)
        self.assertIn("uses: actions/attest@1e69f48acb82d1966a394da916b4c1698aa569d6", wf)
        self.assertNotIn("pip install", wf)
        self.assertNotIn("pull_request:", wf)
        self.assertNotIn("\n  push:", wf)
        uses = [line.strip().split("@", 1)[1] for line in wf.splitlines()
                if line.lstrip().startswith("uses:")]
        self.assertEqual(len(uses), 4)
        for sha in uses:
            self.assertRegex(sha, r"^[a-f0-9]{40}$")


if __name__ == "__main__":
    unittest.main()
