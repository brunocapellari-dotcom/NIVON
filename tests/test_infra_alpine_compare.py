"""Contratos que impedem benchmark Alpine falso, malformado ou usado como release."""
from pathlib import Path
import json
import unittest

from nivon.infra_alpine_compare import NAMES, contar, avaliar
from nivon.infra_supplychain import ErroSupplyChain

ROOT = Path(__file__).resolve().parents[1]


def scan(name, severities):
    return {
        "SchemaVersion": 2, "ArtifactType": "container_image",
        "ArtifactName": name, "Results": [{
            "Target": "synthetic", "Class": "os-pkgs",
            "Vulnerabilities": [{"Severity": sev} for sev in severities],
        }],
    }


class TestAlpineComparison(unittest.TestCase):
    def test_reducao_estatica_nao_libera_ou_prova_musl(self):
        d = scan(NAMES[0], ["HIGH", "HIGH", "CRITICAL"])
        a = scan(NAMES[1], ["HIGH"])
        sbom = {"bomFormat": "CycloneDX", "specVersion": "1.6", "components": [{"name": "python"}]}
        r = avaliar(d, a, sbom, "arm64")
        self.assertEqual(r["delta_blocking_findings"], -2)
        self.assertTrue(r["alpine_has_fewer_findings"])
        self.assertFalse(r["production_authorized"])
        self.assertFalse(r["glibc_to_musl_compatibility_approved"])
        self.assertEqual(r["architecture_of_scan"], "arm64")

    def test_mais_vulnerabilidades_nao_mascara(self):
        d = scan(NAMES[0], [])
        a = scan(NAMES[1], ["CRITICAL"])
        sbom = {"bomFormat": "CycloneDX", "specVersion": "1.6", "components": [{"name": "musl"}]}
        r = avaliar(d, a, sbom, "amd64")
        self.assertEqual(r["delta_blocking_findings"], 1)
        self.assertFalse(r["alpine_has_fewer_findings"])

    def test_imagem_divergente_e_sem_resultados_reprovam(self):
        for mutated in [
            {**scan(NAMES[0], ["HIGH"]), "ArtifactName": "other"},
            {**scan(NAMES[0], []), "Results": []},
            {**scan(NAMES[0], []), "SchemaVersion": 99},
        ]:
            with self.assertRaises(ErroSupplyChain):
                contar(mutated, image=NAMES[0])

    def test_tipo_desconhecido_e_severidade_desconhecida_reprovam(self):
        with self.assertRaises(ErroSupplyChain):
            contar(scan(NAMES[0], ["ULTRA"]), image=NAMES[0])
        wrong = scan(NAMES[0], ["HIGH"])
        wrong["Results"][0]["Class"] = "unknown"
        with self.assertRaises(ErroSupplyChain):
            contar(wrong, image=NAMES[0])

    def test_sem_sbom_e_arch_nao_homologada_falham(self):
        a, b = scan(NAMES[0], []), scan(NAMES[1], [])
        for sbom in ({}, {"bomFormat": "CycloneDX", "specVersion": "1.6", "components": []}):
            with self.assertRaises(ErroSupplyChain):
                avaliar(a, b, sbom, "amd64")
        with self.assertRaises(ErroSupplyChain):
            avaliar(a, b, {"bomFormat":"CycloneDX","specVersion":"1.6",
                           "components":[{"name":"x"}]}, "arm/v8")

    def test_dockerfile_usa_digest_oficial_e_preserva_contrato(self):
        original = (ROOT / "infra/docker/Dockerfile.worker-trim").read_text(encoding="utf-8")
        candidate = (ROOT / "infra/docker/Dockerfile.worker-alpine").read_text(encoding="utf-8")
        from_replaced = "FROM python:3.11.17-alpine3.23@sha256:924d53e01cee5204d35fbcfb71b6c1568c857d7c31141f960ff6a37e111ecc7f"
        self.assertIn(from_replaced, candidate)
        self.assertIn("USER 65532:65532", candidate)
        self.assertIn('ENTRYPOINT ["python", "-m", "nivon.infra_worker"]', candidate)
        self.assertNotIn(from_replaced, original)
        self.assertIn("pip uninstall", candidate)

    def test_ci_native_ambas_arquiteturas_sem_deploy(self):
        wf = (ROOT / ".github/workflows/infra_alpine_benchmark.yml").read_text(encoding="utf-8")
        for s in ("ubuntu-24.04-arm", "ubuntu-latest", "infra_alpine_compare",
                  "persist-credentials: false", "sha256sum -c", "--network=none",
                  "Dockerfile.worker-alpine", "nivon-worker-distro:alpine",
                  "--format cyclonedx", "NIVON_RUNTIME_ENABLED",
                  "--mode synthetic-once", "docker image inspect"):
            self.assertIn(s, wf)
        for bad in ("docker push", "docker login", "secrets.", "upload-artifact@",
                    "pull_request_target:", "continue-on-error: true"):
            self.assertNotIn(bad, wf)


if __name__ == "__main__":
    unittest.main()
