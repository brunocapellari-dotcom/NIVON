"""Integração E2E 9 extras: índice PyPI → release versionada → lote OSV.

Fixtures exercitam exatamente o mesmo código que a CI chama online, sem rede.
"""
from __future__ import annotations

import hashlib
import json
import unittest
from datetime import datetime, timezone
from pathlib import Path

from nivon.radar_compatibilidade_pypi import (
    ALLOWED, _requirements, _select_candidate, executar,
)
from nivon.radar_pypi_osv import BloqueioRadar

PROJECT = (Path(__file__).resolve().parents[1] / "pyproject.toml").read_text()
EXPECTED = {
    "agrobr": "2.0.0", "duckdb": "1.4.2", "mlforecast": "1.8.0",
    "openpyxl": "3.1.6", "pandas": "2.3.1", "pdfplumber": "0.11.7",
    "river": "0.26.0", "scikit-learn": "1.8.0",
    "statsforecast": "2.0.3",
}


def file(name, version, *, yanked=False, sha=None):
    return {
        "filename": f"{name}-{version}-py3-none-any.whl",
        "packagetype": "bdist_wheel", "yanked": yanked,
        "digests": {"sha256": sha or hashlib.sha256((name+version).encode()).hexdigest()},
    }


def endpoint(name, version=None):
    assert name in ALLOWED
    if version is None:
        if name == "duckdb":
            releases = {
                "1.4.1": [file(name, "1.4.1")],
                "1.4.2": [file(name, "1.4.2")],
                "1.4.3": [file(name, "1.4.3", yanked=True)],
                "2.0.0": [file(name, "2.0.0")],
                "1.4.4rc1": [file(name, "1.4.4rc1")],
            }
            latest = "2.0.0"
        else:
            candidate = EXPECTED[name]
            releases = {
                candidate: [file(name, candidate)],
                "99.0.0rc1": [file(name, "99.0.0rc1")],
            }
            latest = candidate
        return json.dumps({
            "info": {"name": name, "version": latest},
            "releases": releases,
        }).encode()
    assert version == EXPECTED[name], (name, version)
    return json.dumps({
        "info": {
            "name": name, "version": version,
            "license_expression": "MIT",
            "requires_dist": ["python-dateutil>=2"],
            "requires_python": ">=3.11",
        },
        "urls": [file(name, version)],
        "vulnerabilities": [{"id": "PYSEC-EXAMPLE"}] if name == "river" else [],
    }).encode()


class CandidatosNoveExtrasTests(unittest.TestCase):
    def mock_fetch(self, url, payload=None):
        if url == "https://api.osv.dev/v1/querybatch":
            assert payload is not None
            queries = json.loads(payload)["queries"]
            self.assertEqual(len(queries), 9)
            self.assertEqual([q["package"]["name"] for q in queries], sorted(ALLOWED))
            self.assertEqual(
                {q["package"]["name"]: q["version"] for q in queries}, EXPECTED)
            return json.dumps({"results": [
                {"vulns": [{"id": "OSV-EXAMPLE"}]} if q["package"]["name"] == "river"
                else {"vulns": []}
                for q in queries
            ]}).encode()
        self.assertTrue(url.startswith("https://pypi.org/pypi/"), url)
        path = url.removeprefix("https://pypi.org/pypi/").split("/")
        self.assertEqual(path[-1], "json")
        name = path[0]
        version = path[1] if len(path) == 3 else None
        return endpoint(name, version)

    def test_real_project_all_nine_direct_extras_selected_and_osv_queried(self):
        result = executar(PROJECT, fetch=self.mock_fetch,
                          observed_at=datetime(2026, 10, 23, tzinfo=timezone.utc))
        self.assertEqual(result["direct_distributions_covered"], 9)
        self.assertEqual(result["pypi_index_json_requests"], 8)
        self.assertEqual(result["pypi_release_json_requests"], 9)
        self.assertEqual(result["osv_batch_queries"], 9)
        self.assertEqual({p["name"]: p["candidate_version"] for p in result["packages"]},
                         EXPECTED)
        self.assertIn(
            {"name": "duckdb", "latest": "2.0.0", "candidate": "1.4.2"},
            result["latest_outside_candidate"],
        )
        self.assertEqual(result["osv_total_ids_reported"], 1)
        self.assertEqual(result["pypi_total_ids_reported"], 1)
        self.assertEqual(result["source"], "INJECTED_RESPONSE_FIXTURES_NOT_LIVE")
        self.assertEqual(len(result["optional_extras_covered"]), 7)
        self.assertIn("ivo-ml", result["optional_extras_covered"])
        for field in ("transitive_dependencies_selected", "full_pep440_pep508_resolved",
                      "python_platform_compatibility_verified",
                      "sha256_claims_checked_against_bytes", "packages_downloaded",
                      "packages_installed", "licenses_legally_approved", "no_cve_claim",
                      "approved_for_install", "approved_for_production"):
            with self.subTest(field=field):
                self.assertIs(result[field], False)

    def test_yanked_latest_numeric_is_not_chosen(self):
        spec = _requirements(PROJECT)["duckdb"]["parsed"]
        result = _select_candidate("duckdb", endpoint("duckdb"), spec)
        self.assertEqual(result["candidate_version"], "1.4.2")
        self.assertEqual(result["pypi_latest_version"], "2.0.0")

    def test_missing_required_extra_is_blocked(self):
        invalid = PROJECT.replace('"pdfplumber>=0.11,<1"', '"untrusted-package>=1,<2"')
        with self.assertRaisesRegex(BloqueioRadar, "allowlist"):
            _requirements(invalid)

    def test_versioned_release_mismatch_fails_entire_radar(self):
        def fail(url, payload=None):
            if url == "https://pypi.org/pypi/duckdb/1.4.2/json":
                obj = json.loads(endpoint("duckdb", "1.4.2"))
                obj["info"]["version"] = "2.0.0"
                return json.dumps(obj).encode()
            return self.mock_fetch(url, payload)
        with self.assertRaisesRegex(BloqueioRadar, "divergente"):
            executar(PROJECT, fetch=fail)

    def test_yanked_or_unhashed_releases_never_become_candidates(self):
        spec = _requirements(PROJECT)["duckdb"]["parsed"]
        data = json.loads(endpoint("duckdb"))
        data["releases"]["1.4.2"][0]["digests"] = {}
        result = _select_candidate("duckdb", json.dumps(data).encode(), spec)
        self.assertEqual(result["candidate_version"], "1.4.1")
        data["releases"]["1.4.1"][0]["yanked"] = True
        with self.assertRaisesRegex(BloqueioRadar, "sem candidato"):
            _select_candidate("duckdb", json.dumps(data).encode(), spec)

    def test_incomplete_osv_batch_rejects_evidence(self):
        def bad(url, payload=None):
            if url == "https://api.osv.dev/v1/querybatch":
                return json.dumps({"results": [{"vulns": []}]}).encode()
            return self.mock_fetch(url, payload)
        with self.assertRaisesRegex(BloqueioRadar, "cardinalidade"):
            executar(PROJECT, fetch=bad)


if __name__ == "__main__":
    unittest.main()
