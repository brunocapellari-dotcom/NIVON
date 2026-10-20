"""Testes offline do inventário de dependências e gates IVO."""
from __future__ import annotations

import copy
import json
import tempfile
import unittest
from pathlib import Path

from nivon.auditoria_extras import (
    ErroDependencias, analisar_requisito, inspecionar, auditar,
)


class DependenciasPreflightTests(unittest.TestCase):
    def setUp(self):
        self.ivo = {"components": [
            {"id": nome, "repository": "https://github.com/example/" + nome.lower()}
            for nome in ("STATSFORECAST", "MLFORECAST", "RIVER", "DUCKDB")
        ]}
        self.toml = (
            '[build-system]\nrequires = ["setuptools>=68"]\n'
            '[project]\nname = "nivon"\ndependencies = []\n'
            '[project.optional-dependencies]\n'
            'forecast = ["pandas>=2.2,<3", "statsforecast>=2,<3"]\n'
            'ivo-ml = ["pandas>=2.2,<3", "mlforecast>=1,<2"]\n'
            'ivo-online = ["river>=0.22,<1"]\n'
            'ivo-query = ["duckdb>=1,<2"]\n'
        )

    def test_success_is_not_security_or_installation_approval(self):
        result = inspecionar(self.toml, self.ivo)
        self.assertEqual(result["direct_packages"], 6)
        self.assertEqual(result["ivo_optional_adapter_gates_checked"],
                         ["DUCKDB", "MLFORECAST", "RIVER", "STATSFORECAST"])
        self.assertIn("setuptools", result["direct_ranges_without_two_sided_bounds"])
        self.assertEqual(result["optional_extras"],
                         ["forecast", "ivo-ml", "ivo-online", "ivo-query"])
        for flag in ("transitive_dependencies_audited", "vulnerabilities_checked",
                     "lockfile_with_hashes_verified", "installed_packages_tested",
                     "performed_installation", "performed_network_request"):
            self.assertFalse(result[flag])
        self.assertTrue(result["release_gate"].startswith("BLOCKED_"))

    def test_exact_and_bounded_are_distinct(self):
        self.assertTrue(analisar_requisito("agrobr==2.0.0")["exact_pin"])
        self.assertTrue(analisar_requisito("mlforecast>=1,<2")["direct_range_bounded"])
        self.assertFalse(analisar_requisito("mlforecast>=1,<2")["exact_pin"])
        self.assertFalse(analisar_requisito("setuptools>=68")["direct_range_bounded"])

    def test_distribution_normalization_and_same_constraints(self):
        req = analisar_requisito("scikit_learn>=1.4,<2")
        self.assertEqual(req["distribution"], "scikit-learn")
        self.assertEqual(analisar_requisito("scikit-learn<2,>=1.4")["constraints"], req["constraints"])

    def test_url_vcs_and_editable_rejected(self):
        for candidate in ("git+https://github.com/a/b", "foo @ https://host/a.whl",
                          "-e ./local", "./wheel.whl", "pkg @ file:///tmp/x.whl"):
            with self.subTest(candidate=candidate), self.assertRaises(ErroDependencias):
                analisar_requisito(candidate)

    def test_unbounded_without_version_rejected(self):
        with self.assertRaises(ErroDependencias):
            analisar_requisito("river")

    def test_markers_and_extra_features_require_review(self):
        for candidate in ("pandas>=2; python_version > '3'", "package[plot]>=1,<2",
                          "package~=1.0"):
            with self.subTest(candidate=candidate), self.assertRaises(ErroDependencias):
                analisar_requisito(candidate)

    def test_pin_plus_range_rejected(self):
        with self.assertRaises(ErroDependencias):
            analisar_requisito("pandas==2,>=2")

    def test_inverted_range_rejected(self):
        with self.assertRaises(ErroDependencias):
            analisar_requisito("pandas>=3,<2")

    def test_equal_range_with_exclusive_limit_rejected(self):
        with self.assertRaises(ErroDependencias):
            analisar_requisito("pandas>=2,<2")

    def test_repeated_clause_rejected(self):
        with self.assertRaises(ErroDependencias):
            analisar_requisito("river>=1,>=1")

    def test_duplicate_within_group_rejected(self):
        with self.assertRaises(ErroDependencias):
            inspecionar(self.toml.replace('"river>=0.22,<1"', '"river>=0.22,<1", "river>=0.22,<1"'),
                       self.ivo)

    def test_conflicting_constraints_across_extras_rejected(self):
        with self.assertRaises(ErroDependencias):
            inspecionar(self.toml.replace('ivo-ml = ["pandas>=2.2,<3"',
                                         'ivo-ml = ["pandas>=2.1,<3"'), self.ivo)

    def test_missing_optional_adaptor_rejected(self):
        cata = copy.deepcopy(self.ivo)
        cata["components"].pop()
        with self.assertRaises(ErroDependencias):
            inspecionar(self.toml, cata)

    def test_moved_optional_to_runtime_rejected(self):
        altered = self.toml.replace("dependencies = []", 'dependencies = ["river>=0.22,<1"]')
        altered = altered.replace('ivo-online = ["river>=0.22,<1"]', 'ivo-online = []')
        with self.assertRaises(ErroDependencias):
            inspecionar(altered, self.ivo)

    def test_invalid_ivo_repository_rejected(self):
        self.ivo["components"][0]["repository"] = "https://github.com.evil.invalid/repo"
        with self.assertRaises(ErroDependencias):
            inspecionar(self.toml, self.ivo)

    def test_bad_extra_array_rejected(self):
        with self.assertRaises(ErroDependencias):
            inspecionar(self.toml.replace('ivo-online = ["river>=0.22,<1"]',
                                         'ivo-online = "river>=0.22,<1"'), self.ivo)

    def test_safe_file_inputs_and_symlink_gate(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp)
            (p / "config").mkdir()
            (p / "pyproject.toml").write_text(self.toml, encoding="utf-8")
            (p / "config/ivo_ferramentas_github.v1.json").write_text(
                json.dumps(self.ivo), encoding="utf-8")
            self.assertEqual(auditar(p)["direct_packages"], 6)
            (p / "pyproject.toml").unlink()
            (p / "pyproject.toml").symlink_to(p / "config/ivo_ferramentas_github.v1.json")
            with self.assertRaises(ErroDependencias):
                auditar(p)

    def test_real_catalog_pyproject_integration(self):
        root = Path(__file__).resolve().parents[1]
        result = auditar(root)
        self.assertGreaterEqual(result["direct_packages"], 8)
        self.assertIn("ivo-ml", result["optional_extras"])
        self.assertIn("ivo-online", result["optional_extras"])
        self.assertIn("ivo-query", result["optional_extras"])
        self.assertFalse(result["vulnerabilities_checked"])


if __name__ == "__main__":
    unittest.main()
