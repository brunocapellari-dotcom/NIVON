"""Paridade entre contratos estáticos NIVON após consolidação do parser.

Nenhuma dependência externa é importada, instalada ou consultada.
"""
from __future__ import annotations

import unittest

from nivon.auditoria_extras import (
    ErroDependencias, analisar_requisito, chave_requisito, inspecionar,
)
from nivon.pesquisa_dependencias import ErroDependencia, inventariar


def projeto(pandas_forecast="pandas>=2.2,<3", pandas_ml="pandas<3.0,>=2.2.0"):
    return (
        '[build-system]\nrequires = ["setuptools>=68"]\n'
        '[project]\nname = "nivon"\nrequires-python = ">=3.11"\n'
        'dependencies = []\n'
        '[project.optional-dependencies]\n'
        f'forecast = ["{pandas_forecast}", "statsforecast>=2,<3"]\n'
        f'ivo-ml = ["{pandas_ml}", "mlforecast>=1,<2"]\n'
        'ivo-online = ["river>=0.22,<1"]\n'
        'ivo-query = ["duckdb>=1,<2"]\n'
    )


IVO = {"components": [
    {"id": id_, "repository": "https://github.com/example/" + id_.lower()}
    for id_ in ("STATSFORECAST", "MLFORECAST", "RIVER", "DUCKDB")
]}


class ConsistenciaParsersTests(unittest.TestCase):
    def test_semantic_equivalence_reorders_and_pads_numeric_versions(self):
        a = analisar_requisito("pandas>=2.2,<3")
        b = analisar_requisito("pandas<3.0.0,>=2.2.0")
        self.assertEqual(chave_requisito(a), chave_requisito(b))

    def test_semantic_difference_operator_is_not_silenced(self):
        a = analisar_requisito("duckdb>1,<2")
        b = analisar_requisito("duckdb>=1,<2")
        self.assertNotEqual(chave_requisito(a), chave_requisito(b))

    def test_two_audits_allow_semantically_equivalent_cross_extra_ranges(self):
        text = projeto()
        first = inspecionar(text, IVO)
        second = inventariar(text)
        self.assertIn("pandas", [p["distribution"] for p in first["packages"]])
        self.assertIn("pandas", [p["distribution"] for p in second["dependencies"]])
        self.assertEqual(first["direct_packages"] - 1, second["direct_distribution_count"])
        self.assertFalse(second["approved_for_production"])
        self.assertFalse(first["vulnerabilities_checked"])

    def test_two_audits_reject_real_conflicting_cross_extra_ranges(self):
        text = projeto(pandas_ml="pandas>=3,<4")
        with self.assertRaises(ErroDependencias):
            inspecionar(text, IVO)
        with self.assertRaises(ErroDependencia):
            inventariar(text)

    def test_two_audits_reject_direct_urls_and_markers(self):
        for invalid in ("pandas @ https://evil.invalid/data.whl",
                        "pandas>=2,<3; platform_system=='Linux'",
                        "pandas[extra]>=2,<3", "../wheel.whl"):
            text = projeto(pandas_ml=invalid)
            with self.subTest(dependency=invalid):
                with self.assertRaises(ErroDependencias):
                    inspecionar(text, IVO)
                with self.assertRaises(ErroDependencia):
                    inventariar(text)

    def test_policy_difference_for_unbounded_runtime_is_explicit(self):
        self.assertFalse(analisar_requisito("example>=1")["direct_range_bounded"])
        text = projeto(pandas_ml="pandas>=2")
        # O pré-voo IVO inventaria a pendência, o inventário mais estrito bloqueia.
        with self.assertRaises(ErroDependencias):
            inspecionar(text, IVO)  # conflita com versão limitada de forecast
        with self.assertRaises(ErroDependencia):
            inventariar(text)

    def test_build_minimum_remains_unpinned_and_risky(self):
        result = inventariar(projeto())
        self.assertEqual(result["build_requirements"][0]["risk"],
                         "BUILD_REQUIRES_MANUAL_RESOLUTION_REVIEW")
        self.assertFalse(result["approved_for_install"])

    def test_equal_endpoints_are_blocked_by_strict_inventory(self):
        # Pré-voo aceita as formas fechadas; inventário estrito não permite ponto único.
        text = projeto(pandas_forecast="pandas>=2,<=2", pandas_ml="pandas>=2.0,<=2.0")
        self.assertIn("pandas", [x["distribution"] for x in inspecionar(text, IVO)["packages"]])
        with self.assertRaises(ErroDependencia):
            inventariar(text)

    def test_no_change_in_pinned_direct_distribution(self):
        text = projeto().replace("duckdb>=1,<2", "duckdb==1.2.0")
        a = inspecionar(text, IVO)
        b = inventariar(text)
        x = next(p for p in a["packages"] if p["distribution"] == "duckdb")
        y = next(p for p in b["dependencies"] if p["distribution"] == "duckdb")
        self.assertTrue(x["exact_pin"])
        self.assertEqual(y["constraints"], "==1.2.0")


if __name__ == "__main__":
    unittest.main()
