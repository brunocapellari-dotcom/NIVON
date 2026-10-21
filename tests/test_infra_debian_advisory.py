"""Testes offline Trivy × Debian oficial: ausência de evidência não é correção."""
import io
import json
from contextlib import redirect_stdout
from pathlib import Path
import tempfile
import unittest

from nivon.infra_debian_advisory import confrontar, main, _tracker_file
from nivon.infra_supplychain import ErroSupplyChain

ROOT = Path(__file__).resolve().parents[1]
WF = ROOT / ".github/workflows/infra_supplychain.yml"


def dados():
    scan = {
        "SchemaVersion": 2, "ArtifactName": "nivon-worker-supply:ci",
        "ArtifactType": "container_image",
        "Results": [
            {"Target": "debian", "Class": "os-pkgs", "Vulnerabilities": [
                {"Severity": "HIGH", "PkgName": "mount", "SrcName": "util-linux", "VulnerabilityID": "CVE-2026-99991"},
                {"Severity": "HIGH", "PkgName": "libmount1", "SrcName": "util-linux", "VulnerabilityID": "CVE-2026-99991"},
                {"Severity": "HIGH", "PkgName": "libmount1", "SrcName": "util-linux", "VulnerabilityID": "CVE-2026-99992"},
                {"Severity": "CRITICAL", "PkgName": "libfoo", "SrcName": "foo", "VulnerabilityID": "CVE-2026-99993"},
                {"Severity": "HIGH", "PkgName": "unknown-binary", "VulnerabilityID": "CVE-2026-99994"},
                {"Severity": "MEDIUM", "PkgName": "ignored", "SrcName": "foo", "VulnerabilityID": "CVE-2026-99995"},
            ]},
            {"Target": "python", "Class": "lang-pkgs", "Vulnerabilities": [
                {"Severity": "HIGH", "PkgName": "wheel", "VulnerabilityID": "GHSA-XXXX"}]},
        ],
    }
    tracker = {
        "util-linux": {
            "CVE-2026-99991": {
                "releases": {"trixie": {"status": "open", "fixed_version": None, "nodsa": "minor"}}},
            "CVE-2026-99992": {
                "releases": {"trixie": {"status": "resolved", "fixed_version": "2.99-1"}}}},
        "foo": {"CVE-2026-99993": {
            "releases": {"trixie": {"status": "resolved", "fixed_version": "<not-affected>"}}}},
    }
    return scan, tracker


class TestDebianAdvisory(unittest.TestCase):
    def test_cve_duplicado_na_familia_gera_par_unico(self):
        scan, tracker = dados()
        x = confrontar(scan, tracker)
        self.assertEqual(x["os_high_critical_findings"], 5)
        self.assertEqual(x["lang_high_critical_findings"], 1)
        self.assertEqual(x["distinct_os_cves"], 4)
        self.assertEqual(x["distinct_source_cve_pairs"], 3)
        self.assertEqual(x["matched_source_cve_pairs"], 3)
        self.assertEqual(x["no_source_mapping_cves"], 1)
        self.assertEqual(x["vendor_status_by_pair"]["open"], 1)
        self.assertEqual(x["vendor_status_by_pair"]["resolved"], 2)
        self.assertEqual(x["fixed_version_declared_pairs"], 1)
        self.assertEqual(x["no_dsa_flagged_pairs"], 1)
        self.assertFalse(x["release_authorized"])
        self.assertTrue(x["vendor_resolved_not_equal_image_fixed"])
        self.assertNotIn("CVE-2026-999", json.dumps(x))

    def test_registro_inexistente_nao_e_corrigido(self):
        scan, tracker = dados()
        del tracker["util-linux"]["CVE-2026-99991"]
        x = confrontar(scan, tracker)
        self.assertEqual(x["no_tracker_entry_pairs"], 1)
        self.assertEqual(x["matched_source_cve_pairs"], 2)

    def test_status_nao_homologado_nao_confirma_patch(self):
        scan, tracker = dados()
        tracker["util-linux"]["CVE-2026-99992"]["releases"]["trixie"] = {
            "status": "other-status", "fixed_version": ""}
        x = confrontar(scan, tracker)
        self.assertEqual(x["vendor_status_by_pair"]["other"], 1)
        self.assertEqual(x["fixed_version_declared_pairs"], 0)

    def test_sem_release_trixie_nao_inferir(self):
        scan, tracker = dados()
        tracker["util-linux"]["CVE-2026-99992"]["releases"] = {
            "bookworm": {"status": "resolved", "fixed_version": "1.2"}}
        x = confrontar(scan, tracker)
        self.assertEqual(x["vendor_status_by_pair"]["other"], 1)

    def test_schema_outro_artefato_e_fonte_sem_pacote_controle(self):
        scan, tracker = dados()
        for data in [{}, {"util-linux": []}, {"foo": {}}]:
            with self.subTest(data=data), self.assertRaises(ErroSupplyChain):
                confrontar(scan, data)
        scan["ArtifactName"] = "outro:ci"
        with self.assertRaises(ErroSupplyChain):
            confrontar(scan, tracker)

    def test_id_incompativel_bloqueado(self):
        scan, tracker = dados()
        scan["Results"][0]["Vulnerabilities"][0]["VulnerabilityID"] = "GHSA-UNKNOWN"
        with self.assertRaises(ErroSupplyChain):
            confrontar(scan, tracker)

    def test_sem_os_high_critical_recusado(self):
        scan, tracker = dados()
        scan["Results"][0]["Vulnerabilities"] = []
        with self.assertRaises(ErroSupplyChain):
            confrontar(scan, tracker)

    def test_fonte_nao_homologada_conta_sem_mapeamento(self):
        scan, tracker = dados()
        scan["Results"][0]["Vulnerabilities"][0]["SrcName"] = "../bad"
        x = confrontar(scan, tracker)
        self.assertEqual(x["no_source_mapping_cves"], 2)

    def test_snapshot_json_duplicado_ou_link_recusado(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            f = base / "tracker.json"
            f.write_text("{}", encoding="utf-8")
            with self.assertRaises(ErroSupplyChain):
                _tracker_file(f)
            f.write_text(json.dumps(dados()[1]), encoding="utf-8")
            self.assertIn("util-linux", _tracker_file(f))
            link = base / "link.json"
            link.symlink_to(f)
            with self.assertRaises(ErroSupplyChain):
                _tracker_file(link)

    def test_cli_processa_snapshot_de_fixture_sem_expor_ids(self):
        scan, tracker = dados()
        with tempfile.TemporaryDirectory() as tmp:
            a = Path(tmp) / "trivy.json"
            b = Path(tmp) / "debian.json"
            a.write_text(json.dumps(scan), encoding="utf-8")
            b.write_text(json.dumps(tracker), encoding="utf-8")
            f = io.StringIO()
            with redirect_stdout(f):
                rc = main(["--trivy-json", str(a), "--debian-tracker-json", str(b)])
            self.assertEqual(rc, 0)
            out = json.loads(f.getvalue())
            self.assertFalse(out["release_authorized"])
            self.assertIn("collection_date_utc", out)
            self.assertNotIn("CVE-2026-999", f.getvalue())

    def test_workflow_reconcilia_depois_de_scan_e_gate_nao_e_mascarado(self):
        w = WF.read_text(encoding="utf-8")
        self.assertIn("security-tracker.debian.org/tracker/data/json", w)
        self.assertIn("python -m nivon.infra_debian_advisory", w)
        self.assertIn("--max-filesize 25000000", w)
        self.assertIn("if: ${{ !cancelled() }}", w)
        self.assertLess(w.index("python -m nivon.infra_debian_advisory"),
                        w.index("python -m nivon.infra_supplychain"))
        for b in ("--ignore-unfixed", "continue-on-error: true", "docker push"):
            self.assertNotIn(b, w)


if __name__ == "__main__":
    unittest.main()
