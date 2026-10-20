"""Regressões offline da governança de pesquisa tecnológica."""
from __future__ import annotations

import copy
import json
import tempfile
import unittest
from pathlib import Path

from nivon.pesquisa_tecnologica import (
    ARQUIVO_DELTA, ARQUIVO_IVO, POLITICA, ErroPesquisa, auditar, validar_catalogos,
)


class PesquisaTecnologicaTests(unittest.TestCase):
    def setUp(self):
        self.ivo = {"project": "NIVON", "components": [
            {"id": "STATSFORECAST", "repository": "https://github.com/Nixtla/statsforecast"}]}
        self.item = {"id": "DLT_INGEST", "repository": "https://github.com/dlt-hub/dlt",
                     "python_distribution": "dlt", "purpose": "Ingestão incremental",
                     "priority": "P0", "decision": "BENCHMARK", "license_declared": "Apache-2.0",
                     "evidence_url": "https://github.com/dlt-hub/dlt/blob/devel/LICENSE.txt",
                     "reviewed_on": "2026-10-20", "overlap": "coleta nativa",
                     "next_experiment": "backtest offline", "license_reviewed": False,
                     "security_reviewed": False, "dependencies_reviewed": False,
                     "benchmark_passed": False, "allow_install": False}
        self.delta = {"project": "NIVON", "schema_version": "1.0",
                      "extends": ARQUIVO_IVO, "policy": POLITICA, "candidates": [self.item]}
        self.toml = "[project]\nname = 'nivon'\ndependencies = []\n[project.optional-dependencies]\nforecast = ['statsforecast>=2,<3']\n"

    def verify(self, ivo=None, delta=None, toml=None):
        return validar_catalogos(ivo if ivo is not None else self.ivo,
                                 delta if delta is not None else self.delta,
                                 toml if toml is not None else self.toml)

    def test_unified_inventory_and_no_auto_install(self):
        r = self.verify()
        self.assertEqual(r["total_unique_repositories"], 2)
        self.assertEqual(r["decisions"], {"BENCHMARK": 1})
        self.assertEqual(len(r["candidates"][0]["gates_missing"]), 4)
        self.assertFalse(r["auto_install_enabled"])

    def test_duplicate_repository_against_ivo(self):
        self.item["repository"] = "https://github.com/nixtla/StatsForecast"
        with self.assertRaises(ErroPesquisa):
            self.verify()

    def test_duplicate_id_against_ivo(self):
        self.item["id"] = "STATSFORECAST"
        with self.assertRaises(ErroPesquisa):
            self.verify()

    def test_duplicate_repo_within_delta(self):
        dup = copy.deepcopy(self.item)
        dup["id"] = "DLT_EXTRA"
        self.delta["candidates"].append(dup)
        with self.assertRaises(ErroPesquisa):
            self.verify()

    def test_reject_non_github_or_unsafe_urls(self):
        for url in ("http://github.com/dlt-hub/dlt", "https://github.com.evil.io/a/b",
                    "https://github.com/u:p@github.com/a/b", "https://github.com/dlt-hub/dlt?ref=x",
                    "https://github.com/dlt-hub/dlt/tree/main"):
            self.item["repository"] = url
            with self.subTest(url=url), self.assertRaises(ErroPesquisa):
                self.verify()

    def test_evidence_must_be_same_repo(self):
        self.item["evidence_url"] = "https://github.com/another/repo/blob/main/LICENSE"
        with self.assertRaises(ErroPesquisa):
            self.verify()

    def test_reject_policy_relaxation(self):
        self.delta["policy"] = "ALLOW_ALL"
        with self.assertRaises(ErroPesquisa):
            self.verify()

    def test_reject_auto_install_even_with_review(self):
        self.item["allow_install"] = True
        with self.assertRaises(ErroPesquisa):
            self.verify()

    def test_reject_pretend_approved(self):
        self.item["decision"] = "ADOPT"
        with self.assertRaises(ErroPesquisa):
            self.verify()

    def test_adopt_only_with_complete_evidence_no_install(self):
        self.item.update(decision="ADOPT", license_reviewed=True, security_reviewed=True,
                         dependencies_reviewed=True, benchmark_passed=True)
        r = self.verify()
        self.assertEqual(r["candidates"][0]["gates_missing"], [])
        self.assertFalse(r["auto_install_enabled"])

    def test_reject_string_false_in_boolean_gate(self):
        self.item["security_reviewed"] = "false"
        with self.assertRaises(ErroPesquisa):
            self.verify()

    def test_reject_existing_declared_dependency(self):
        with self.assertRaises(ErroPesquisa):
            self.verify(toml=self.toml.replace("statsforecast", "dlt"))

    def test_reject_future_date_and_bad_distributions(self):
        self.item["reviewed_on"] = "2999-01-01"
        with self.assertRaises(ErroPesquisa):
            self.verify()
        self.item["reviewed_on"] = "2026-10-20"
        self.item["python_distribution"] = "dlt; rm -rf /"
        with self.assertRaises(ErroPesquisa):
            self.verify()

    def test_local_integration_and_symlink_gate(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "config").mkdir()
            (root / ARQUIVO_IVO).write_text(json.dumps(self.ivo), encoding="utf-8")
            (root / ARQUIVO_DELTA).write_text(json.dumps(self.delta), encoding="utf-8")
            (root / "pyproject.toml").write_text(self.toml, encoding="utf-8")
            self.assertEqual(auditar(root)["research_delta_items"], 1)
            (root / ARQUIVO_DELTA).unlink()
            (root / ARQUIVO_DELTA).symlink_to(root / ARQUIVO_IVO)
            with self.assertRaises(ErroPesquisa):
                auditar(root)

    def test_broken_json_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "config").mkdir()
            (root / ARQUIVO_IVO).write_text("{not json", encoding="utf-8")
            with self.assertRaises(ErroPesquisa):
                auditar(root)


if __name__ == "__main__":
    unittest.main()
