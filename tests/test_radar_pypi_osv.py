"""Fluxo de integração do radar público PyPI/OSV com respostas simuladas.

Os testes exercitam coleta, resolução de release, checksums publicados,
correlação OSV por versão e estados bloqueados. A CI executa o mesmo fluxo
com APIs reais somente em job separado e estritamente limitado.
"""
from __future__ import annotations

import hashlib
import json
import unittest
from datetime import datetime, timezone

from nivon.radar_pypi_osv import BloqueioRadar, executar

PROJECT = '''[project]
name="nivon"
version="0.1.0"
[project.optional-dependencies]
agro=["agrobr==2.0.0"]
ivo-query=["duckdb>=1,<2"]
ivo-online=["river>=0.22,<1"]
ivo-ml=["pandas>=2.2,<3","mlforecast>=1,<2"]
'''
VERSIONS = {"agrobr": "2.0.0", "duckdb": "1.4.1",
            "mlforecast": "1.7.2", "river": "0.24.0"}


def project(name: str, version: str) -> bytes:
    data = {
        "info": {
            "name": name, "version": version, "license_expression": "MIT",
            "license": None, "requires_dist": ["numpy>=1,<3"],
            "requires_python": ">=3.11",
        },
        "last_serial": 1234,
        "urls": [{
            "filename": f"{name}-{version}-py3-none-any.whl",
            "packagetype": "bdist_wheel",
            "digests": {"sha256": hashlib.sha256(name.encode()).hexdigest()},
            "yanked": False, "upload_time_iso_8601": "2026-01-01T00:00:00Z",
        }],
    }
    return json.dumps(data).encode()


class RadarIntegradoTests(unittest.TestCase):
    def fetch_pypi(self, url):
        name = url.split("/")[4]
        self.assertIn(name, VERSIONS)
        if name == "agrobr":
            self.assertEqual(url, "https://pypi.org/pypi/agrobr/2.0.0/json")
        return project(name, VERSIONS[name])

    def fetch_osv(self, url, raw):
        self.assertEqual(url, "https://api.osv.dev/v1/querybatch")
        parsed = json.loads(raw)
        self.assertEqual(len(parsed["queries"]), 4)
        self.assertEqual([x["package"]["name"] for x in parsed["queries"]],
                         sorted(VERSIONS))
        for item in parsed["queries"]:
            self.assertEqual(item["version"],
                             VERSIONS[item["package"]["name"]])
        results = []
        for pkg in parsed["queries"]:
            name = pkg["package"]["name"]
            results.append({"vulns": [{"id": "OSV-FAKE-1", "modified": "2026-01-01"}]
                            if name == "duckdb" else []})
        return json.dumps({"results": results}).encode()

    def executar_radar(self, fetch_pypi=None, fetch_osv=None):
        return executar(PROJECT, pypi_fetch=fetch_pypi or self.fetch_pypi,
                        osv_fetch=fetch_osv or self.fetch_osv,
                        now=datetime(2026, 10, 23, tzinfo=timezone.utc))

    def test_full_four_release_pipeline_and_security_boundaries(self):
        result = self.executar_radar()
        self.assertEqual(result["queried_package_count"], 4)
        self.assertEqual(result["osv_total_ids_reported"], 1)
        self.assertEqual([p["name"] for p in result["packages"]],
                         sorted(VERSIONS))
        self.assertEqual(result["packages"][0]["version"], "2.0.0")
        self.assertTrue(all(p["release_files"][0]["sha256_official_claim"]
                            for p in result["packages"]))
        for k in ("all_optional_extras_covered", "full_dependency_resolution",
                  "wheel_bytes_downloaded", "wheels_installed",
                  "actual_wheel_contents_inspected",
                  "osv_complete_universe_of_cves_proven",
                  "legal_license_review_completed", "approved_for_install",
                  "approved_for_production"):
            with self.subTest(k=k):
                self.assertIs(result[k], False)

    def test_reject_missing_wheel_digest_from_pypi(self):
        def bad(url):
            obj = json.loads(self.fetch_pypi(url))
            obj["urls"][0]["digests"] = {}
            return json.dumps(obj).encode()
        with self.assertRaisesRegex(BloqueioRadar, "hash"):
            self.executar_radar(fetch_pypi=bad)

    def test_osv_pagination_blocks_incomplete_live_report(self):
        def incomplete(url, raw):
            return json.dumps({"results": [
                {"vulns": [], "next_page_token": "more"},
                {"vulns": []}, {"vulns": []}, {"vulns": []}
            ]}).encode()
        with self.assertRaisesRegex(BloqueioRadar, "paginou"):
            self.executar_radar(fetch_osv=incomplete)

    def test_osv_wrong_cardinality_blocks_all_results(self):
        def incomplete(url, raw):
            return json.dumps({"results": [{"vulns": []}]}).encode()
        with self.assertRaisesRegex(BloqueioRadar, "cardinalidade"):
            self.executar_radar(fetch_osv=incomplete)

    def test_pypi_version_substitution_is_rejected_for_fixed_agrobr(self):
        def wrong(url):
            obj = json.loads(self.fetch_pypi(url))
            if "/agrobr/" in url:
                obj["info"]["version"] = "1.0.0"
            return json.dumps(obj).encode()
        with self.assertRaisesRegex(BloqueioRadar, "versão"):
            self.executar_radar(fetch_pypi=wrong)


if __name__ == "__main__":
    unittest.main()
