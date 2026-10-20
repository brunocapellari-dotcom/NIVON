"""Regressões da auditoria de dependências diretas, sem pip/rede."""
from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from nivon.pesquisa_dependencias import ErroDependencia, auditar, inventariar


def toml(core="", extras="alpha = ['pandas>=2.2,<3', 'duckdb>=1,<2']",
         build="['setuptools>=68']", python=">=3.11"):
    return (f"[build-system]\nrequires = {build}\n"
            f"build-backend = 'setuptools.build_meta'\n"
            f"[project]\nname = 'nivon'\nrequires-python = '{python}'\n"
            f"dependencies = [{core}]\n"
            f"[project.optional-dependencies]\n{extras}\n")


class DependenciasAuditTests(unittest.TestCase):
    def test_range_and_build_pending(self):
        r = inventariar(toml())
        self.assertEqual(r["direct_distribution_count"], 2)
        self.assertEqual(r["dependencies"][0]["constraints"], ">=1,<2")
        self.assertEqual(r["dependencies"][1]["distribution"], "pandas")
        self.assertEqual(r["build_requirements"][0]["risk"], "BUILD_REQUIRES_MANUAL_RESOLUTION_REVIEW")
        self.assertFalse(r["approved_for_install"])
        self.assertFalse(r["known_vulnerabilities_checked"])

    def test_fully_pinned_build_declared_not_installed(self):
        r = inventariar(toml(build="['setuptools==68.2.1']"))
        self.assertIsNone(r["build_requirements"][0]["risk"])
        self.assertFalse(r["installed_packages_verified"])

    def test_normalization_and_dedup_groups(self):
        r = inventariar(toml(
            extras="alpha = ['My_Lib>=1.0,<2']\nbeta = ['my-lib>=1,<2', 'duckdb==1.2.1']"))
        # Contract treats >=1.0 and >=1 as equivalent only by numeric comparison?
        self.assertEqual(r["direct_distribution_count"], 2)

    def test_strict_constraint_conflict_rejected(self):
        with self.assertRaises(ErroDependencia):
            inventariar(toml(extras="alpha=['pandas>=2.2,<3']\nbeta=['pandas>=3,<4']"))

    def test_duplicate_package_in_extra(self):
        with self.assertRaises(ErroDependencia):
            inventariar(toml(extras="alpha=['pandas>=2,<3','Pandas>=2,<3']"))

    def test_duplicate_extra_normalized(self):
        with self.assertRaises(ErroDependencia):
            inventariar(toml(extras="A_B=['duckdb==1.1']\na-b=['pandas==2.2']"))

    def test_unbounded_requirement_rejected(self):
        for item in ["duckdb>=1", "pandas<3", "duckdb", "duckdb~=1.1"]:
            with self.subTest(item=item), self.assertRaises(ErroDependencia):
                inventariar(toml(extras=f"alpha=['{item}']"))

    def test_direct_url_marker_and_unsafe_references(self):
        for item in ["duckdb @ https://evil.test/file.whl",
                     "pandas>=2,<3; sys_platform=='linux'",
                     "pandas[fast]>=2,<3",
                     "git+https://evil.test/repo",
                     "../localpackage"]:
            with self.subTest(item=item), self.assertRaises(ErroDependencia):
                inventariar(toml(extras=f"alpha=[{json.dumps(item)}]"))

    def test_empty_or_reverse_bounds(self):
        for item in ["pandas>=3,<2", "pandas>3,<=3", "pandas>=2,>=3",
                     "pandas<3,<4", "pandas==2,>=1"]:
            with self.subTest(item=item), self.assertRaises(ErroDependencia):
                inventariar(toml(extras=f"alpha=['{item}']"))

    def test_exact_pin_accepted(self):
        r = inventariar(toml(core="'agrobr==2.0.0'", extras=""))
        self.assertEqual(r["default_runtime_dependency_count"], 1)
        self.assertEqual(r["dependencies"][0]["constraints"], "==2.0.0")

    def test_invalid_python_contract(self):
        with self.assertRaises(ErroDependencia):
            inventariar(toml(python=">=3.7"))

    def test_no_direct_dependencies_has_empty_inventory(self):
        r = inventariar(toml(extras=""))
        self.assertEqual(r["direct_distribution_count"], 0)
        self.assertFalse(r["transitive_sbom_generated"])

    def test_reproducible_hash_and_deterministic_manifest(self):
        src = toml()
        a, b = inventariar(src), inventariar(src)
        self.assertEqual(a, b)
        self.assertEqual(len(a["pyproject_sha256"]), 64)
        self.assertNotEqual(a["pyproject_sha256"], inventariar(src + "\n")["pyproject_sha256"])

    def test_strange_types_fail_closed(self):
        for extras in ("alpha = 42", "alpha = ['pandas>=2,<3', 12]"):
            with self.subTest(extras=extras), self.assertRaises(ErroDependencia):
                inventariar(toml(extras=extras))

    def test_reject_symlink_project_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp)
            (p / "original.toml").write_text(toml(), encoding="utf-8")
            (p / "pyproject.toml").symlink_to(p / "original.toml")
            with self.assertRaises(ErroDependencia):
                auditar(p)

    def test_actual_repository_pyproject(self):
        root = Path(__file__).resolve().parents[1]
        r = auditar(root)
        self.assertEqual(r["default_runtime_dependency_count"], 0)
        self.assertIn("ivo-ml", r["optional_extras"])
        self.assertIn("ivo-online", r["optional_extras"])
        self.assertIn("ivo-query", r["optional_extras"])
        self.assertFalse(r["approved_for_production"])


if __name__ == "__main__":
    unittest.main()
