"""Regressões em lote para o analisador de tags de wheel, sem downloads."""
from __future__ import annotations

import copy
import unittest

from nivon.inspecao_compatibilidade_wheels import (
    _dependencies, _filename_tag, _python_range, analisar
)
from nivon.radar_pypi_osv import BloqueioRadar

NAMES = ("agrobr", "duckdb", "mlforecast", "openpyxl", "pandas",
         "pdfplumber", "river", "scikit-learn", "statsforecast")


def fixture():
    items = []
    for name in NAMES:
        version = "1.2.3"
        wheel = name.replace("-", "_") + "-1.2.3-py3-none-any.whl"
        items.append({
            "name": name, "version": version, "candidate_version": version,
            "direct_numeric_range_satisfied": True,
            "requires_python": ">=3.9,<3.13",
            "release_files": [{
                "filename": wheel, "type": "bdist_wheel",
                "requires_python": ">=3.9,<3.13", "yanked": False,
            }],
            "requires_dist_declared": [
                "numpy>=1.24,<3",
                "typing-extensions>=4; python_version < '3.12'",
                "pytest; extra == 'test'",
            ],
        })
    return {
        "schema": "NIVON_ALL_EXTRAS_PYPI_OSV_CANDIDATES_V1",
        "generated_utc": "2026-10-23T16:00:00Z",
        "direct_distributions_covered": 9,
        "packages": items,
        "approved_for_install": False,
        "approved_for_production": False,
        "full_pep440_pep508_resolved": False,
        "packages_downloaded": False,
    }


class CompatibilidadeWheelE2ETests(unittest.TestCase):
    def test_integrated_nine_packages_and_transitive_unresolved_names(self):
        report = analisar(fixture())
        self.assertEqual(report["packages_examined"], 9)
        self.assertEqual(report["package_status_counts"],
                         {"WHEEL_TAG_AND_PYTHON_RANGE_MATCH_METADATA_ONLY": 9})
        self.assertEqual(report["declared_unresolved_dependency_names"],
                         ["numpy", "pytest", "typing-extensions"])
        self.assertFalse(report["full_pep508_dependency_resolution"])
        self.assertFalse(report["all_packages_compatible"])
        self.assertFalse(report["approved_for_install"])
        self.assertFalse(report["approved_for_production"])
        self.assertEqual(report["packages"][0]["matching_wheels"][0]["requires_python_status"],
                         "MATCHES")

    def test_cpython311_manylinux_and_abi3_tag(self):
        for filename in [
            "duckdb-1.2.3-cp311-cp311-manylinux_2_17_x86_64.whl",
            "duckdb-1.2.3-cp311-cp311-manylinux2014_x86_64.whl",
            "duckdb-1.2.3-cp38-abi3-manylinux_2_12_x86_64.whl",
            "duckdb-1.2.3-py2.py3-none-any.whl",
            "duckdb-1.2.3-cp311-abi3-manylinux_2_5_x86_64.whl",
        ]:
            with self.subTest(filename=filename):
                self.assertEqual(_filename_tag(filename, "duckdb", "1.2.3"),
                                 "MATCHES_SUPPORTED_TAG_SUBSET")

    def test_other_architectures_and_newer_glibc_excluded(self):
        for filename in [
            "duckdb-1.2.3-cp312-cp312-manylinux_2_17_x86_64.whl",
            "duckdb-1.2.3-cp311-cp311-win_amd64.whl",
            "duckdb-1.2.3-cp311-cp311-manylinux_2_28_x86_64.whl",
            "duckdb-1.2.3-cp311-cp311-manylinux_2_17_aarch64.whl",
            "duckdb-1.2.3-cp311-cp311-musllinux_1_2_x86_64.whl",
        ]:
            with self.subTest(filename=filename):
                self.assertEqual(_filename_tag(filename, "duckdb", "1.2.3"),
                                 "NO_TAG_IN_SUPPORTED_SUBSET")

    def test_unknown_linux_nonportable_is_not_counted_as_match(self):
        self.assertEqual(
            _filename_tag("duckdb-1.2.3-cp311-cp311-linux_x86_64.whl",
                          "duckdb", "1.2.3"),
            "UNKNOWN_NON_PORTABLE_LINUX_TAG",
        )

    def test_python_version_ranges_tristate(self):
        matrix = [
            (">=3.8,<4", "MATCHES"),
            (">=3.11", "MATCHES"),
            ("~=3.8", "UNKNOWN"),
            (">=3.12", "EXCLUDES"),
            ("<3.11", "EXCLUDES"),
            (">=3.9,!=3.11.*", "UNKNOWN"),
            ("==3.11", "MATCHES"),
            (None, "UNKNOWN"),
            ("", "UNKNOWN"),
        ]
        for expr, expected in matrix:
            with self.subTest(expr=expr):
                self.assertEqual(_python_range(expr), expected)

    def test_package_python_exclusion_supersedes_wheel_filename(self):
        data = fixture()
        data["packages"][0]["requires_python"] = ">=3.12"
        data["packages"][0]["release_files"][0]["requires_python"] = ">=3.12"
        report = analisar(data)
        self.assertEqual(report["packages"][0]["wheel_metadata_status"],
                         "PYTHON_VERSION_EXCLUDED_BY_RELEASE_METADATA")
        self.assertEqual(len(report["packages"][0]["matching_wheels"]), 0)

    def test_no_supported_wheel_blocks_metadata_suitability(self):
        data = fixture()
        data["packages"][0]["release_files"][0]["filename"] = (
            "agrobr-1.2.3-cp312-cp312-win_amd64.whl")
        report = analisar(data)
        self.assertEqual(report["packages"][0]["wheel_metadata_status"],
                         "NO_MATCHING_WHEEL_IN_SUPPORTED_SUBSET")

    def test_missing_requires_python_remains_uncertain(self):
        data = fixture()
        data["packages"][0]["requires_python"] = None
        data["packages"][0]["release_files"][0]["requires_python"] = None
        report = analisar(data)
        self.assertEqual(report["packages"][0]["wheel_metadata_status"],
                         "WHEEL_COMPATIBILITY_UNCERTAIN")

    def test_wheel_filename_does_not_prove_hash(self):
        report = analisar(fixture())
        self.assertFalse(report["full_packaging_tags_implementation"])
        self.assertFalse(report["glibc_abi_runtime_verified"])
        self.assertFalse(report["wheels_downloaded"])

    def test_untrusted_inventory_cannot_claim_release(self):
        for key in ("approved_for_install", "approved_for_production",
                    "packages_downloaded", "full_pep440_pep508_resolved"):
            data = fixture()
            data[key] = True
            with self.subTest(key=key), self.assertRaisesRegex(
                    BloqueioRadar, "falsamente homologado"):
                analisar(data)

    def test_requires_dist_names_not_mistaken_for_full_resolution(self):
        deps = _dependencies([
            "numpy>=2", "colorama; sys_platform == 'win32'",
            "typer[all]>=0.10", "numpy>=1,<3",
        ])
        self.assertEqual(deps["unconditional"], ["numpy"])
        self.assertEqual(deps["conditional_or_extras"], ["colorama", "typer"])
        self.assertTrue(deps["requires_dist_present"])
        self.assertFalse(deps["unparsed"])


if __name__ == "__main__":
    unittest.main()
