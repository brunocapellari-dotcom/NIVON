"""Teste do ensaio de hardening; não confundir redução de CVEs com release."""
import copy
import json
from pathlib import Path
import tempfile
import unittest

from nivon.infra_trim_compare import NAMES, comparar, contar, main
from nivon.infra_supplychain import ErroSupplyChain

ROOT = Path(__file__).resolve().parents[1]


def scan(which, severities):
    return {
        "SchemaVersion": 2,
        "ArtifactName": NAMES[which],
        "ArtifactType": "container_image",
        "Results": [{
            "Target": "os:synthetic", "Class": "os-pkgs",
            "Vulnerabilities": [
                {"Severity": s, "VulnerabilityID": f"SYNTHETIC-{i}"}
                for i, s in enumerate(severities)
            ]
        }],
    }


class TestTrimCompare(unittest.TestCase):
    def test_reduz_achados_sem_poder_libera_producao(self):
        result = comparar(scan("base", ["HIGH", "CRITICAL", "MEDIUM"]),
                          scan("trim", ["HIGH", "LOW"]))
        self.assertEqual(result["blockers_before"], 2)
        self.assertEqual(result["blockers_after"], 1)
        self.assertEqual(result["delta_blockers"], -1)
        self.assertTrue(result["candidate_reduces_blockers"])
        self.assertFalse(result["production_allowed"])
        self.assertFalse(result["candidate_adopted"])
        self.assertFalse(result["arm64_runtime_validated"])

    def test_arm64_rotulo_do_scan_nao_simula_execucao_nativa(self):
        result = comparar(scan("base", ["HIGH"]), scan("trim", []),
                          architecture="arm64")
        self.assertEqual(result["scan_architecture"], "arm64")
        self.assertFalse(result["candidate_amd64_only"])
        # Execução real e segurança do runner são observadas no workflow, não no JSON.
        self.assertFalse(result["arm64_runtime_validated"])
        self.assertFalse(result["production_allowed"])

    def test_arquitetura_que_nao_foi_homologada_e_recusada(self):
        with self.assertRaises(ErroSupplyChain):
            comparar(scan("base", []), scan("trim", []), architecture="s390x")

    def test_candidato_pior_nao_escondido(self):
        result = comparar(scan("base", []), scan("trim", ["CRITICAL"]))
        self.assertEqual(result["delta_blockers"], 1)
        self.assertFalse(result["candidate_reduces_blockers"])

    def test_imagem_diferente_bloqueada(self):
        wrong = scan("base", ["HIGH"])
        wrong["ArtifactName"] = "fake"
        with self.assertRaises(ErroSupplyChain):
            comparar(wrong, scan("trim", []))

    def test_scan_vazio_reprovado(self):
        bad = scan("base", [])
        bad["Results"] = []
        with self.assertRaises(ErroSupplyChain):
            comparar(bad, scan("trim", []))

    def test_severidade_invalida_reprovada(self):
        with self.assertRaises(ErroSupplyChain):
            contar(scan("base", ["OTHER"]), name=NAMES["base"])

    def test_sem_achados_nao_e_release(self):
        result = comparar(scan("base", []), scan("trim", []))
        self.assertFalse(result["production_allowed"])
        self.assertEqual(result["blockers_after"], 0)

    def test_cli_em_fixtures_locais(self):
        with tempfile.TemporaryDirectory() as tmp:
            before = Path(tmp) / "before.json"
            after = Path(tmp) / "after.json"
            before.write_text(json.dumps(scan("base", ["HIGH"])), encoding="utf-8")
            after.write_text(json.dumps(scan("trim", [])), encoding="utf-8")
            import io
            from contextlib import redirect_stdout
            out = io.StringIO()
            with redirect_stdout(out):
                status = main(["--baseline", str(before), "--candidate", str(after)])
            self.assertEqual(status, 0)
            self.assertFalse(json.loads(out.getvalue())["production_allowed"])

    def test_dockerfile_experimental_preserva_baseline(self):
        base = (ROOT / "infra/docker/Dockerfile.worker").read_text(encoding="utf-8")
        candidate = (ROOT / "infra/docker/Dockerfile.worker-trim").read_text(encoding="utf-8")
        self.assertNotIn("pip uninstall", base)
        self.assertIn("pip uninstall", candidate)
        self.assertIn("python:3.11-slim-trixie@sha256:", candidate)
        self.assertIn("USER 65532:65532", candidate)
        self.assertNotIn("curl ", candidate)
        self.assertNotIn("apt-get", candidate)

    def test_workflow_ensaio_sem_release(self):
        wf = (ROOT / ".github/workflows/infra_trim_benchmark.yml").read_text(encoding="utf-8")
        for required in ("sha256sum -c", "--network=none", "infra_trim_compare",
                         "Dockerfile.worker-trim", "persist-credentials: false"):
            self.assertIn(required, wf)
        for banned in ("docker push", "docker login", "upload-artifact@",
                       "continue-on-error: true", "pull_request_target:", "secrets."):
            self.assertNotIn(banned, wf)


if __name__ == "__main__":
    unittest.main()
