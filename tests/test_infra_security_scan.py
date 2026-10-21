"""Contrato de revisão Trivy/SBOM sem instalação ou scanner externo."""
import copy
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from nivon.infra_security_scan import (
    ErroSecurityReport, EXPECTED_IMAGE, avaliar_relatorios, _load
)


class TestInfraSecurityScan(unittest.TestCase):
    def setUp(self):
        self.scan = {
            "SchemaVersion": 2,
            "ArtifactName": EXPECTED_IMAGE,
            "ArtifactType": "container_image",
            "Metadata": {"ImageID": "sha256:" + "a" * 64},
            "Results": [
                {"Target": "debian:12", "Class": "os-pkgs",
                 "Type": "debian", "Vulnerabilities": None},
                {"Target": "python", "Class": "lang-pkgs",
                 "Type": "python-pkg", "Vulnerabilities": []},
            ],
        }
        self.bom = {
            "bomFormat": "CycloneDX",
            "specVersion": "1.6",
            "components": [
                {"type": "library", "name": "python", "version": "3.11"},
                {"type": "library", "name": "openssl", "version": "3"}
            ],
        }

    def test_sem_cve_nao_libera_producao(self):
        status = avaliar_relatorios(self.scan, self.bom)
        self.assertEqual(status["status"], "SCAN_CLEAN_BUT_RELEASE_BLOCKED")
        self.assertEqual(status["sbom_components"], 2)
        self.assertEqual(status["scanned_targets"], 2)
        self.assertEqual(status["vulnerabilities"]["CRITICAL"], 0)
        self.assertFalse(status["release_authorized"])
        self.assertFalse(status["backup_remote_verified"])

    def test_critical_bloqueado_com_trilha(self):
        self.scan["Results"][0]["Vulnerabilities"] = [{
            "VulnerabilityID": "CVE-2026-99999",
            "PkgName": "openssl",
            "Severity": "CRITICAL",
        }]
        result = avaliar_relatorios(self.scan, self.bom)
        self.assertEqual(result["vulnerabilities"]["CRITICAL"], 1)
        self.assertIn("HIGH_CRITICAL_CVES_REQUIRE_TRIAGE", result["review_reasons"])
        self.assertEqual(result["distinct_affected_packages"], 1)
        self.assertFalse(result["release_authorized"])

    def test_desconhecido_e_medio_pedem_revisao(self):
        self.scan["Results"][0]["Vulnerabilities"] = [
            {"VulnerabilityID": "CVE-2026-2", "PkgName": "foo", "Severity": "MEDIUM"},
            {"VulnerabilityID": "CVE-2026-3", "PkgName": "foo", "Severity": "UNKNOWN"},
        ]
        res = avaliar_relatorios(self.scan, self.bom)
        self.assertIn("UNKNOWN_SEVERITIES_REQUIRE_TRIAGE", res["review_reasons"])
        self.assertIn("MEDIUM_CVES_REQUIRE_RELEASE_REVIEW", res["review_reasons"])

    def test_sem_results_falha_fechada(self):
        self.scan["Results"] = []
        with self.assertRaises(ErroSecurityReport):
            avaliar_relatorios(self.scan, self.bom)

    def test_scan_de_outro_artefato_bloqueado(self):
        self.scan["ArtifactName"] = "outro:latest"
        with self.assertRaises(ErroSecurityReport):
            avaliar_relatorios(self.scan, self.bom)

    def test_sem_sbom_nao_promove(self):
        self.bom["components"] = []
        with self.assertRaises(ErroSecurityReport):
            avaliar_relatorios(self.scan, self.bom)

    def test_metadados_ou_classes_desconhecidos(self):
        self.scan["Metadata"] = {}
        with self.assertRaises(ErroSecurityReport):
            avaliar_relatorios(self.scan, self.bom)
        self.scan["Metadata"]["ImageID"] = "sha256:" + "a" * 64
        self.scan["Results"][0]["Class"] = "other"
        with self.assertRaises(ErroSecurityReport):
            avaliar_relatorios(self.scan, self.bom)

    def test_severidade_invalida_rejeitada(self):
        self.scan["Results"][0]["Vulnerabilities"] = [
            {"VulnerabilityID": "CVE-A", "PkgName": "pkg", "Severity": "NONE"}
        ]
        with self.assertRaises(ErroSecurityReport):
            avaliar_relatorios(self.scan, self.bom)

    def test_json_duplicado_rejeitado(self):
        with tempfile.TemporaryDirectory() as tmp:
            f=Path(tmp)/"scan.json"
            f.write_text('{"ArtifactName":"safe","ArtifactName":"evil"}',encoding="utf-8")
            with self.assertRaises(ErroSecurityReport):
                _load(f)

    def test_arquivo_inexistente_nao_e_criado(self):
        with tempfile.TemporaryDirectory() as tmp:
            f=Path(tmp)/"absent.json"
            with self.assertRaises(ErroSecurityReport):
                _load(f)
            self.assertFalse(f.exists())

    def test_cli_analisa_sem_autorizar(self):
        root=Path(__file__).resolve().parents[1]
        with tempfile.TemporaryDirectory() as tmp:
            vuln=Path(tmp)/"v.json";bom=Path(tmp)/"bom.json"
            vuln.write_text(json.dumps(self.scan),encoding="utf-8")
            bom.write_text(json.dumps(self.bom),encoding="utf-8")
            cmd=[sys.executable,"-m","nivon.infra_security_scan",
                 "--vulnerabilities",str(vuln),"--sbom",str(bom)]
            env=dict(os.environ,PYTHONPATH=str(root/"src"))
            run=subprocess.run(cmd,cwd=root,env=env,capture_output=True,
                               text=True,timeout=15,check=False)
            self.assertEqual(run.returncode,0,run.stderr)
            out=json.loads(run.stdout)
            self.assertFalse(out["release_authorized"])
            strict=subprocess.run(cmd+["--require-release-ready"],cwd=root,env=env,
                                  capture_output=True,text=True,timeout=15,check=False)
            self.assertEqual(strict.returncode,3)

if __name__=="__main__":
    unittest.main()
