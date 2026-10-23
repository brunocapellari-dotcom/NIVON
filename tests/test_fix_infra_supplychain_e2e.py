"""Regressão integrada dos gates de supply chain NIVON (PR #10).

Somente inspeção de arquivos locais e fixtures Trivy/CycloneDX sintéticas.
Nenhum scanner, download, rede, segredo, Docker build ou deploy é executado.
"""
from __future__ import annotations

import unittest
from pathlib import Path

from nivon.infra_supplychain import avaliar_relatorios, ErroSupplyChain


RAIZ = Path(__file__).resolve().parents[1]
WF = RAIZ / ".github" / "workflows" / "infra_supplychain.yml"
DOCKER = RAIZ / "infra" / "docker" / "Dockerfile.worker"
IMAGEM = "nivon-worker-supply:ci"


def evidencias(*, nome_sbom: str = IMAGEM) -> tuple[dict, dict]:
    scan = {
        "SchemaVersion": 2, "ArtifactName": IMAGEM,
        "ArtifactType": "container_image",
        "Results": [{
            "Target": "debian:synthetic",
            "Vulnerabilities": [],
        }],
    }
    sbom = {
        "bomFormat": "CycloneDX", "specVersion": "1.6",
        "metadata": {"component": {"type": "container", "name": nome_sbom}},
        "components": [{"name": "python:synthetic"}, {"name": "libc:synthetic"}],
    }
    return scan, sbom


class TestAuditoriaSupplyChainIndependente(unittest.TestCase):
    def test_controle_scanner_imagem_sbom_coerentes_nao_autoriza_producao(self):
        scan, sbom = evidencias()
        resultado = avaliar_relatorios(scan, sbom, imagem=IMAGEM)
        self.assertEqual(resultado["estado"], "STATIC_SCAN_NO_HIGH_CRITICAL")
        self.assertFalse(resultado["producao_autorizada"])

    def test_controle_achado_high_bloqueia_sem_go_live(self):
        scan, sbom = evidencias()
        scan["Results"][0]["Vulnerabilities"] = [{
            "Severity": "HIGH", "VulnerabilityID": "FALHA_SINTETICA",
        }]
        resultado = avaliar_relatorios(scan, sbom, imagem=IMAGEM)
        self.assertEqual(resultado["estado"], "BLOCKED_HIGH_CRITICAL")
        self.assertFalse(resultado["producao_autorizada"])
        self.assertEqual(resultado["bloqueantes"], 1)

    def test_p0_alteracao_inventory_usado_no_docker_dispara_supplychain(self):
        docker = DOCKER.read_text(encoding="utf-8")
        fluxo = WF.read_text(encoding="utf-8")
        self.assertIn("COPY infra/inventory.v1.json", docker)
        self.assertTrue(
            any(("'infra/inventory.v1.json'" in linha
                 or "'infra/**'" in linha
                 or "'infra/**/*'" in linha)
                for linha in fluxo.splitlines() if linha.strip().startswith("- ")),
            "P0: Docker COPY infra/inventory.v1.json muda conteúdo da imagem, "
            "mas o gate supply chain não observa esse caminho em pull_request.paths",
        )

    def test_p1_sbom_da_imagem_incorreta_nao_prova_imagem_inspecionada(self):
        scan, sbom = evidencias(nome_sbom="outra-imagem:ci")
        with self.assertRaises(
            ErroSupplyChain,
            msg="P1: SBOM declara outra imagem e não pode compor evidência "
                "com relatório Trivy da imagem selecionada",
        ):
            avaliar_relatorios(scan, sbom, imagem=IMAGEM)


if __name__ == "__main__":
    unittest.main()
