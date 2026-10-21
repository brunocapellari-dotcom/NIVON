"""Testes sem rede dos contratos de supply chain e do workflow GitHub."""
import copy
import json
from pathlib import Path
import tempfile
import unittest

from nivon.infra_supplychain import (
    _carregar_json, avaliar_relatorios, ErroSupplyChain, main,
)

ROOT = Path(__file__).resolve().parents[1]
WF = ROOT / ".github/workflows/infra_supplychain.yml"
IMAGE = "nivon-worker-supply:ci"


def fixtures():
    scan = {
        "SchemaVersion": 2,
        "ArtifactName": IMAGE,
        "ArtifactType": "container_image",
        "Results": [{"Target": "debian", "Vulnerabilities": []}],
    }
    bom = {
        "bomFormat": "CycloneDX", "specVersion": "1.6",
        "components": [{"name": "python"}, {"name": "debian"}],
    }
    return scan, bom


class TestSupplyChain(unittest.TestCase):
    def test_limpo_nao_promove_producao(self):
        scan, bom = fixtures()
        result = avaliar_relatorios(scan, bom, imagem=IMAGE)
        self.assertEqual(result["estado"], "STATIC_SCAN_NO_HIGH_CRITICAL")
        self.assertEqual(result["sbom_componentes"], 2)
        self.assertEqual(result["bloqueantes"], 0)
        self.assertFalse(result["producao_autorizada"])
        self.assertFalse(result["imagem_arm64_escaneada"])

    def test_critical_e_high_bloqueiam(self):
        scan, bom = fixtures()
        scan["Results"][0]["Vulnerabilities"] = [
            {"Severity": "HIGH", "VulnerabilityID": "SYNTHETIC_ONE"},
            {"Severity": "CRITICAL", "VulnerabilityID": "SYNTHETIC_TWO"},
        ]
        r = avaliar_relatorios(scan, bom, imagem=IMAGE)
        self.assertEqual(r["bloqueantes"], 2)
        self.assertEqual(r["estado"], "BLOCKED_HIGH_CRITICAL")
        self.assertEqual(r["vulnerabilidades_por_severidade"]["CRITICAL"], 1)

    def test_relatorio_vazio_ou_tipo_falso_nao_passam(self):
        s, b = fixtures()
        for mutation in [
            lambda q: q.update(Results=[]),
            lambda q: q.update(ArtifactType="filesystem"),
            lambda q: q.update(ArtifactName="outro:ci"),
            lambda q: q.update(SchemaVersion="2"),
            lambda q: q.update(Results=[{"Target": "x", "Vulnerabilities": None}]),
        ]:
            z = copy.deepcopy(s)
            mutation(z)
            with self.assertRaises(ErroSupplyChain):
                avaliar_relatorios(z, b, imagem=IMAGE)
        with self.assertRaises(ErroSupplyChain):
            avaliar_relatorios(s, b, imagem="other:ci")

    def test_sbom_ausente_falha(self):
        s, b = fixtures()
        for bad in [{}, {"bomFormat": "CycloneDX", "specVersion": "1.6"},
                    {"bomFormat": "CycloneDX", "specVersion": "1.6", "components": []}]:
            with self.assertRaises(ErroSupplyChain):
                avaliar_relatorios(s, bad, imagem=IMAGE)

    def test_severidade_invalida_falha(self):
        s, b = fixtures()
        s["Results"][0]["Vulnerabilities"] = [{"Severity": "HIGH_FAKE"}]
        with self.assertRaises(ErroSupplyChain):
            avaliar_relatorios(s, b, imagem=IMAGE)

    def test_duplicacao_json_e_symlink_bloqueados(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            p = base / "scan.json"
            p.write_text('{"a":1,"a":2}', encoding="utf-8")
            with self.assertRaises(ErroSupplyChain):
                _carregar_json(p)
            p.write_text(json.dumps(fixtures()[0]), encoding="utf-8")
            link = base / "linked.json"
            link.symlink_to(p)
            with self.assertRaises(ErroSupplyChain):
                _carregar_json(link)

    def test_cli_bloqueia_vulnerabilidade_e_nao_imprime_identificador(self):
        s, b = fixtures()
        s["Results"][0]["Vulnerabilities"] = [
            {"Severity": "CRITICAL", "VulnerabilityID": "SENSITIVE_FAKE_SENTINEL"}
        ]
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            a, z = base / "scan.json", base / "bom.json"
            a.write_text(json.dumps(s), encoding="utf-8")
            z.write_text(json.dumps(b), encoding="utf-8")
            import contextlib
            from io import StringIO
            out = StringIO()
            with contextlib.redirect_stdout(out):
                status = main(["--trivy-json", str(a), "--cyclonedx-json",
                               str(z), "--image", IMAGE])
            self.assertEqual(status, 3)
            self.assertNotIn("SENSITIVE_FAKE_SENTINEL", out.getvalue())
            self.assertEqual(json.loads(out.getvalue())["bloqueantes"], 1)

    def test_workflow_pinned_tools_sem_deploy_sem_secrets_actions(self):
        raw = WF.read_text(encoding="utf-8")
        for must in [
            "contents: read", "persist-credentials: false",
            "fetch-depth: 0", "gitleaks_8.30.1_linux_x64.tar.gz",
            "trivy_0.76.0_Linux-64bit.tar.gz", "sha256sum -c",
            "gitleaks git", "trivy image", "--format cyclonedx",
            "infra_supplychain", "nivon-worker-supply:ci",
        ]:
            self.assertIn(must, raw)
        for forbidden in [
            "pull_request_target:", "schedule:", "push:", "docker push",
            "docker login", "secrets.", "upload-artifact@", "--ignore-unfixed",
            "--exit-code 0", "continue-on-error: true",
        ]:
            self.assertNotIn(forbidden, raw)
        self.assertRegex(raw, r"checkout@[0-9a-f]{40}")
        self.assertNotIn("gitleaks-action@", raw)


if __name__ == "__main__":
    unittest.main()
