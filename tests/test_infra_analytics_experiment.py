"""Contratos e testes sintéticos (sem depender de Agrobr, pandas e StatsForecast)."""
import math
from pathlib import Path
import unittest

from nivon.infra_analytics_probe import validar_previsao, ProbeBlocked, main as probe_main
from nivon.infra_analytics_audit import ARTIFACTS, auditar
from nivon.infra_supplychain import ErroSupplyChain
from nivon.infra_optional_wheels import EXPECTED

ROOT = Path(__file__).resolve().parents[1]


def scan(name, levels):
    return {"SchemaVersion": 2, "ArtifactType": "container_image",
            "ArtifactName": name, "Results": [
                {"Class": "os-pkgs", "Target": "synthetic:debian",
                 "Vulnerabilities": [{"Severity": s} for s in levels]}]}


def sbom(components=("agrobr", "pandas", "statsforecast")):
    return {"bomFormat": "CycloneDX", "specVersion": "1.6",
            "components": [{"name": name, "type": "library"} for name in components]}


class TestAnalyticsExperiment(unittest.TestCase):
    def test_previsao_naive_rejeita_dados_invalidos(self):
        validar_previsao([8.0, 8.0], expected=8.0)
        for invalid in ([1, 8], [8], ["8", 8], [True, 8], [math.nan, 8],
                        [math.inf, 8], [8, 8, 8]):
            with self.subTest(invalid=invalid), self.assertRaises(ProbeBlocked):
                validar_previsao(invalid, expected=8.0)

    def test_sem_flag_de_ativacao_probe_inerte(self):
        self.assertEqual(probe_main([]), 0)

    def test_scan_agrega_risco_e_nao_libera_producao(self):
        data = auditar(scan(ARTIFACTS["baseline"], ["HIGH"]),
                       scan(ARTIFACTS["candidate"], ["HIGH", "CRITICAL"]),
                       sbom(), "arm64")
        self.assertEqual(data["additional_blocking_findings"], 1)
        self.assertEqual(data["analytics_blocking_findings"], 2)
        self.assertFalse(data["production_authorized"])
        self.assertFalse(data["analytics_image_adopted"])

    def test_scan_sem_resultado_ou_schema_invalido_e_bloqueado(self):
        bad = scan(ARTIFACTS["candidate"], [])
        bad["Results"] = []
        with self.assertRaises(ErroSupplyChain):
            auditar(scan(ARTIFACTS["baseline"], []), bad, sbom(), "amd64")
        with self.assertRaises(ErroSupplyChain):
            auditar(scan(ARTIFACTS["baseline"], []), scan(ARTIFACTS["candidate"], []),
                    sbom(("pandas",)), "amd64")

    def test_pyproject_e_dockerfile_contem_extras_imutaveis_do_ensaio(self):
        self.assertEqual(EXPECTED["agro"], ("agrobr==2.0.0",))
        self.assertEqual(EXPECTED["forecast"], ("pandas>=2.2,<3", "statsforecast>=2,<3"))
        docker=(ROOT / "infra/docker/Dockerfile.analytics-experiment").read_text(encoding="utf-8")
        for required in ("FROM python:3.11-slim-trixie@sha256:", "COPY --from=wheelhouse",
                         "--no-index", "--only-binary=:all:", '"agrobr==2.0.0"',
                         '"statsforecast>=2,<3"', "USER 65532:65532"):
            self.assertIn(required, docker)
        self.assertEqual(docker.count("FROM python:3.11-slim-trixie@sha256:"), 2)
        self.assertNotIn("curl ", docker)
        self.assertNotIn("apt-get", docker)

    def test_workflow_isolado_e_sem_release(self):
        workflow=(ROOT / ".github/workflows/infra_analytics_experiment.yml").read_text(encoding="utf-8")
        for signal in ("ubuntu-24.04-arm", "ubuntu-latest", "pypi.org/simple",
                       "wheelhouse=", "--network=none", "--network none",
                       "--only-binary=:all:", "--no-index", "persist-credentials: false",
                       "sha256sum -c", "--format cyclonedx", "infra_analytics_audit",
                       "infra_analytics_probe", "--offline-synthetic", "--cap-drop ALL",
                       "--read-only", "docker image inspect", "NUMBA_NUM_THREADS=1"):
            self.assertIn(signal, workflow)
        for forbidden in ("docker push", "docker login", "upload-artifact@",
                          "secrets.", "pull_request_target:", "continue-on-error: true"):
            self.assertNotIn(forbidden, workflow)


if __name__ == "__main__":
    unittest.main()
