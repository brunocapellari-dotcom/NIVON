"""Testes sintéticos do verificador de proveniência de artefatos GitHub Actions.

Não consulta rede. O módulo sob teste permite consulta ao GitHub apenas quando
invocado explicitamente; os dados de fixture NÃO atestam origem real.
"""
from __future__ import annotations

import hashlib
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from nivon.auditoria_evidencias_pacotes import ErroEvidencia
from nivon.proveniencia_github import (
    ARTIFACT_NAME, REPO, WORKFLOW, _json_unico, consultar_api,
    validar_metadados, verificar_github,
)


SHA = "a" * 40
RUN_ID = 123
ARTIFACT_ID = 567


class EvidenciaGitHubTests(unittest.TestCase):
    def setUp(self):
        self.ctx = tempfile.TemporaryDirectory()
        self.addCleanup(self.ctx.cleanup)
        self.zip_path = Path(self.ctx.name) / "evidencia.zip"
        self.bytes = b"Synthetic artifact: NOT an actual GitHub archive"
        self.zip_path.write_bytes(self.bytes)
        self.sha = hashlib.sha256(self.bytes).hexdigest()
        self.run = {
            "id": RUN_ID, "event": "workflow_dispatch", "status": "completed",
            "conclusion": "success", "head_sha": SHA, "path": WORKFLOW,
            "repository": {"id": 99, "full_name": REPO},
            "head_repository": {"id": 99, "full_name": REPO},
        }
        self.art = {
            "id": ARTIFACT_ID, "name": ARTIFACT_NAME, "expired": False,
            "digest": "sha256:" + self.sha, "size_in_bytes": len(self.bytes),
            "workflow_run": {
                "id": RUN_ID, "repository_id": 99,
                "head_repository_id": 99, "head_sha": SHA,
            },
        }

    def offline(self):
        return validar_metadados(
            self.run, self.art, self.sha, len(self.bytes),
            run_id=RUN_ID, artifact_id=ARTIFACT_ID, source_sha=SHA,
        )

    def online_mock(self):
        def get(endpoint, *, token=None):
            self.assertIsNone(token)
            if endpoint.endswith("/runs/123"):
                return self.run
            if endpoint.endswith("/artifacts/567"):
                return self.art
            raise AssertionError(endpoint)
        with patch("nivon.proveniencia_github.consultar_api", side_effect=get) as call:
            result = verificar_github(
                self.zip_path, run_id=RUN_ID,
                artifact_id=ARTIFACT_ID, source_sha=SHA,
            )
            self.assertEqual(call.call_count, 2)
            return result

    def test_offline_consistency_never_authenticates_service(self):
        res = self.offline()
        self.assertEqual(res["archive_sha256"], self.sha)
        self.assertTrue(res["artifact_digest_matches_github_api"])
        self.assertFalse(res["live_api_query_done_by_this_function"])
        for flag in (
            "github_sigstore_attestation_verified", "slsa_provenance_verified",
            "archive_contents_verified", "third_party_wheel_origin_authenticated",
            "workflow_runner_trusted_or_hardened", "pip_audit_execution_proven",
            "approved_for_install", "approved_for_production",
        ):
            with self.subTest(flag=flag):
                self.assertFalse(res[flag])

    def test_mocked_live_path_hashes_file_but_does_not_sign(self):
        res = self.online_mock()
        self.assertTrue(res["live_api_query_done_by_this_function"])
        self.assertEqual(res["archive_bytes"], len(self.bytes))
        self.assertFalse(res["github_sigstore_attestation_verified"])

    def test_modified_local_archive_with_unchanged_api_digest_rejected(self):
        self.zip_path.write_bytes(self.bytes + b"modified")
        with patch("nivon.proveniencia_github.consultar_api", side_effect=[
            self.run, self.art,
        ]):
            with self.assertRaisesRegex(ErroEvidencia, "tamanho|digest"):
                verificar_github(self.zip_path, run_id=RUN_ID,
                                 artifact_id=ARTIFACT_ID, source_sha=SHA)

    def test_forged_reported_digest_rejected(self):
        self.art["digest"] = "sha256:" + "0" * 64
        with self.assertRaisesRegex(ErroEvidencia, "digest"):
            self.offline()

    def test_artifact_size_mismatch_rejected(self):
        self.art["size_in_bytes"] += 1
        with self.assertRaisesRegex(ErroEvidencia, "tamanho"):
            self.offline()

    def test_artifact_expired_rejected(self):
        self.art["expired"] = True
        with self.assertRaisesRegex(ErroEvidencia, "artefato"):
            self.offline()

    def test_artifact_wrong_name_rejected(self):
        self.art["name"] = "untrusted"
        with self.assertRaisesRegex(ErroEvidencia, "artefato"):
            self.offline()

    def test_artifact_from_different_run_rejected(self):
        self.art["workflow_run"]["id"] += 1
        with self.assertRaisesRegex(ErroEvidencia, "artefato"):
            self.offline()

    def test_repository_id_mismatch_rejected(self):
        self.art["workflow_run"]["repository_id"] += 1
        with self.assertRaisesRegex(ErroEvidencia, "artefato"):
            self.offline()

    def test_fork_identity_rejected(self):
        self.run["head_repository"]["full_name"] = "unknown/other"
        with self.assertRaisesRegex(ErroEvidencia, "identidade"):
            self.offline()

    def test_wrong_head_sha_rejected(self):
        self.run["head_sha"] = "b" * 40
        with self.assertRaisesRegex(ErroEvidencia, "identidade"):
            self.offline()

    def test_pull_request_run_not_a_manual_evidence_run(self):
        self.run["event"] = "pull_request"
        with self.assertRaisesRegex(ErroEvidencia, "manual"):
            self.offline()

    def test_non_successful_run_rejected(self):
        for status, conclusion in [
            ("completed", "failure"), ("in_progress", None),
            ("completed", "cancelled"),
        ]:
            with self.subTest(status=status, conclusion=conclusion):
                self.run["status"] = status
                self.run["conclusion"] = conclusion
                with self.assertRaisesRegex(ErroEvidencia, "sucesso"):
                    self.offline()

    def test_wrong_workflow_rejected(self):
        self.run["path"] = ".github/workflows/testes.yml"
        with self.assertRaisesRegex(ErroEvidencia, "workflow"):
            self.offline()

    def test_run_path_ref_suffix_is_allowed_if_file_exact(self):
        self.run["path"] = WORKFLOW + "@refs/heads/main"
        self.assertEqual(self.offline()["workflow_path"], WORKFLOW)

    def test_extra_url_is_not_trusted(self):
        with self.assertRaisesRegex(ErroEvidencia, "allowlist"):
            consultar_api("/repos/attacker/other/actions/runs/123")

    def test_urls_cannot_contain_query_or_redirect(self):
        for uri in (
            "/repos/brunocapellari-dotcom/NIVON/actions/runs/123?redirect=1",
            "/repos/brunocapellari-dotcom/NIVON/actions/artifacts/-1",
            "https://attacker.invalid",
        ):
            with self.subTest(uri=uri), self.assertRaises(ErroEvidencia):
                consultar_api(uri)

    def test_invalid_input_never_makes_network_request(self):
        with patch("nivon.proveniencia_github.consultar_api") as client:
            with self.assertRaisesRegex(ErroEvidencia, "identificadores"):
                verificar_github(self.zip_path, run_id=RUN_ID,
                                 artifact_id=ARTIFACT_ID, source_sha="invalid")
            client.assert_not_called()

    def test_symlink_local_archive_rejected(self):
        symlink = Path(self.ctx.name) / "artifact-link.zip"
        symlink.symlink_to(self.zip_path)
        with patch("nivon.proveniencia_github.consultar_api") as client:
            with self.assertRaisesRegex(ErroEvidencia, "symlink"):
                verificar_github(symlink, run_id=RUN_ID,
                                 artifact_id=ARTIFACT_ID, source_sha=SHA)
            client.assert_not_called()

    def test_json_duplicate_keys_rejected(self):
        raw = b'{"id":1,"id":2}'
        with self.assertRaisesRegex(ErroEvidencia, "duplicada"):
            _json_unico(raw)

    def test_json_too_big_fails_closed(self):
        with self.assertRaisesRegex(ErroEvidencia, "excessiva"):
            _json_unico(b"x" * 1_000_001)

    def test_json_root_list_rejected(self):
        with self.assertRaisesRegex(ErroEvidencia, "objeto"):
            _json_unico(b"[]")

    def test_token_header_newline_rejected_before_http(self):
        with self.assertRaisesRegex(ErroEvidencia, "token"):
            consultar_api("/repos/brunocapellari-dotcom/NIVON/actions/runs/123",
                          token="abc\nmalicious")

    def test_non_sha_digest_algorithm_rejected(self):
        self.art["digest"] = "md5:" + "b" * 32
        with self.assertRaisesRegex(ErroEvidencia, "digest"):
            self.offline()

    def test_bad_workflow_filter_rejected(self):
        with self.assertRaisesRegex(ErroEvidencia, "workflow esperado"):
            validar_metadados(self.run, self.art, self.sha, len(self.bytes),
                              run_id=RUN_ID, artifact_id=ARTIFACT_ID, source_sha=SHA,
                              workflow="../untrusted.yaml")


if __name__ == "__main__":
    unittest.main()
