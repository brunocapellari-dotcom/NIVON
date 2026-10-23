"""Regressão local da triagem CVE: rastreabilidade e sem liberação de release."""
from __future__ import annotations

import copy
import io
import json
from contextlib import redirect_stdout
from pathlib import Path
import tempfile
import unittest

from nivon.infra_cve_triage import EXPECTED_IMAGE, triar_vulnerabilidades, main
from nivon.infra_supplychain import ErroSupplyChain

ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github/workflows/infra_supplychain.yml"


def scan():
    return {
        "SchemaVersion": 2,
        "ArtifactName": EXPECTED_IMAGE,
        "ArtifactType": "container_image",
        "Results": [
            {"Target": "debian", "Class": "os-pkgs", "Vulnerabilities": [
                {"Severity": "HIGH", "PkgName": "libssl3t64",
                 "VulnerabilityID": "CVE-TEST-ONE", "FixedVersion": "3.5.4"},
                {"Severity": "HIGH", "PkgName": "libssl3t64",
                 "VulnerabilityID": "CVE-TEST-TWO", "FixedVersion": ""},
                {"Severity": "CRITICAL", "PkgName": "libc6",
                 "VulnerabilityID": "CVE-TEST-THREE"},
                {"Severity": "MEDIUM", "PkgName": "curl",
                 "VulnerabilityID": "CVE-TEST-MEDIUM"},
            ]},
            {"Target": "python-pkg", "Class": "lang-pkgs",
             "Vulnerabilities": None},
        ],
    }


class TestCveTriage(unittest.TestCase):
    def test_agrupa_por_pacote_sem_revelar_cve(self):
        x = triar_vulnerabilidades(scan())
        self.assertEqual(x["blocking_findings"], 3)
        self.assertEqual(x["high"], 2)
        self.assertEqual(x["critical"], 1)
        self.assertEqual(x["fixed_version_reported"], 1)
        self.assertEqual(x["no_fixed_version_reported"], 2)
        self.assertEqual(x["affected_packages"], 2)
        self.assertEqual(x["top_packages"][0]["package"], "libc6")
        self.assertFalse(x["production_authorized"])
        self.assertNotIn("CVE-TEST", json.dumps(x))

    def test_repeticao_da_mesma_cve_em_pacotes_diferentes(self):
        s = scan()
        s["Results"][0]["Vulnerabilities"].append({
            "Severity": "HIGH", "PkgName": "libcrypto3",
            "VulnerabilityID": "CVE-TEST-ONE"
        })
        x = triar_vulnerabilidades(s)
        self.assertEqual(x["blocking_findings"], 4)
        self.assertEqual(x["distinct_vulnerability_ids"], 3)
        self.assertEqual(x["repeated_findings_vs_distinct_ids"], 1)
        self.assertEqual(x["ids_affecting_multiple_packages"], 1)
        self.assertEqual(x["blocking_by_package_class"], {
            "os-pkgs": 4, "lang-pkgs": 0
        })
        self.assertEqual(x["largest_shared_vulnerability_groups"][0]["affected_packages"], 2)
        self.assertEqual(x["largest_shared_vulnerability_groups"][0]["findings"], 2)
        self.assertNotIn("CVE-TEST", json.dumps(x))
        self.assertFalse(x["production_authorized"])
        self.assertTrue(x["release_gate_unchanged"])

    def test_mesma_cve_no_mesmo_pacote_conta_achado_mas_nao_novo_grupo(self):
        s = scan()
        s["Results"][0]["Vulnerabilities"].append({
            "Severity": "HIGH", "PkgName": "libssl3t64",
            "VulnerabilityID": "CVE-TEST-ONE"
        })
        x = triar_vulnerabilidades(s)
        self.assertEqual(x["blocking_findings"], 4)
        self.assertEqual(x["distinct_vulnerability_ids"], 3)
        self.assertEqual(x["ids_affecting_multiple_packages"], 0)

    def test_separacao_de_pacotes_sistema_linguagem(self):
        s = scan()
        s["Results"][1]["Vulnerabilities"] = [{
            "Severity": "HIGH", "PkgName": "wheel",
            "VulnerabilityID": "GHSA-EXEMPLO-123"
        }]
        x = triar_vulnerabilidades(s)
        self.assertEqual(x["blocking_by_package_class"], {
            "os-pkgs": 3, "lang-pkgs": 1
        })
        self.assertEqual(x["distinct_vulnerability_ids"], 4)

    def test_identificador_com_quebra_de_linha_recusado(self):
        s = scan()
        s["Results"][0]["Vulnerabilities"][0]["VulnerabilityID"] = "CVE-TEST\\n::warning::"
        with self.assertRaises(ErroSupplyChain):
            triar_vulnerabilidades(s)

    def test_sem_cves_nao_autoriza_release(self):
        s = scan()
        s["Results"][0]["Vulnerabilities"] = []
        x = triar_vulnerabilidades(s)
        self.assertEqual(x["blocking_findings"], 0)
        self.assertFalse(x["production_authorized"])
        self.assertEqual(x["status"], "NO_HIGH_CRITICAL_REPORTED")

    def test_relatorios_errados_bloqueiam(self):
        s = scan()
        for change in (
            lambda d: d.update(SchemaVersion=3),
            lambda d: d.update(ArtifactName="outro"),
            lambda d: d.update(ArtifactType="filesystem"),
            lambda d: d.update(Results=[]),
            lambda d: d["Results"][0].update(Class="unknown"),
            lambda d: d["Results"][0].update(Target=""),
            lambda d: d["Results"][0].update(Vulnerabilities={}),
        ):
            with self.subTest(change=repr(change)):
                bad = copy.deepcopy(s)
                change(bad)
                with self.assertRaises(ErroSupplyChain):
                    triar_vulnerabilidades(bad)

    def test_nome_pacote_malicioso_recusado(self):
        for candidate in ("evil\n::warning::", "../sneaky", "", " "):
            with self.subTest(candidate=candidate):
                s = scan()
                s["Results"][0]["Vulnerabilities"][0]["PkgName"] = candidate
                with self.assertRaises(ErroSupplyChain):
                    triar_vulnerabilidades(s)

    def test_identificador_ausente_reprovado(self):
        s = scan()
        s["Results"][0]["Vulnerabilities"][0]["VulnerabilityID"] = ""
        with self.assertRaises(ErroSupplyChain):
            triar_vulnerabilidades(s)

    def test_severidade_desconhecida_reprovada(self):
        s = scan()
        s["Results"][0]["Vulnerabilities"][0]["Severity"] = "ULTRA"
        with self.assertRaises(ErroSupplyChain):
            triar_vulnerabilidades(s)

    def test_sem_fixed_version_nao_inferir_patch(self):
        s = scan()
        s["Results"][0]["Vulnerabilities"][0]["FixedVersion"] = None
        x = triar_vulnerabilidades(s)
        self.assertEqual(x["fixed_version_reported"], 0)
        self.assertEqual(x["no_fixed_version_reported"], 3)
        self.assertTrue(x["scan_is_not_proof_of_fix"])

    def test_limite_pacotes_trunca_exibicao_mas_nao_totais(self):
        s = scan()
        s["Results"][0]["Vulnerabilities"] = [
            {"Severity": "HIGH", "PkgName": f"lib-{i}",
             "VulnerabilityID": f"CVE-TEST-{i}"}
            for i in range(27)
        ]
        out = triar_vulnerabilidades(s)
        self.assertEqual(out["affected_packages"], 27)
        self.assertEqual(len(out["top_packages"]), 25)
        self.assertTrue(out["top_packages_truncated"])
        self.assertEqual(out["blocking_findings"], 27)

    def test_cli_retorna_0_para_triagem_sem_liberar_pipeline(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / "vuln.json"
            p.write_text(json.dumps(scan()), encoding="utf-8")
            buffer = io.StringIO()
            with redirect_stdout(buffer):
                code = main(["--trivy-json", str(p)])
            self.assertEqual(code, 0)
            result = json.loads(buffer.getvalue())
            self.assertEqual(result["status"], "REMEDIATION_REQUIRED")
            self.assertFalse(result["production_authorized"])
            self.assertNotIn("CVE-TEST", buffer.getvalue())

    def test_cli_invalido_falha_fechada(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "missing.json"
            buffer = io.StringIO()
            with redirect_stdout(buffer):
                code = main(["--trivy-json", str(path)])
            self.assertEqual(code, 2)
            self.assertEqual(json.loads(buffer.getvalue())["status"], "INVALID_TRIAGE_BLOCKED")

    def test_workflow_triagem_antes_do_gate_sem_waiver(self):
        workflow = WORKFLOW.read_text(encoding="utf-8")
        self.assertIn("python -m nivon.infra_cve_triage", workflow)
        self.assertLess(workflow.index("python -m nivon.infra_cve_triage"),
                        workflow.index("python -m nivon.infra_supplychain"))
        self.assertNotIn("continue-on-error: true", workflow)
        self.assertNotIn("--ignore-unfixed", workflow)
        self.assertNotIn("docker push", workflow)


if __name__ == "__main__":
    unittest.main()
