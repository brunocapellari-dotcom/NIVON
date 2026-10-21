"""Gate local de consolidação meteorológica, sem rede ou acesso externo.

Garante a identidade dos seis arquivos copiados das PRs 9/11 e impede
reabilitação acidental de módulos/fonte; isso NÃO prova skill preditiva,
licenças ou independência de dados históricos.
"""
from __future__ import annotations

import hashlib
import json
import unittest
from pathlib import Path

from nivon.pacotes_chuva_asof import _PREVISOES
from nivon.registro_motores import MODULOS


ROOT = Path(__file__).resolve().parents[1]


def _load(path):
    return json.loads((ROOT / path).read_text(encoding="utf-8"))


def _git_blob_sha1(data: bytes) -> str:
    return hashlib.sha1(b"blob " + str(len(data)).encode("ascii") + b"\0" + data).hexdigest()


class TestConsolidacaoMeteoHidro(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.manifest = _load("config/integracao_meteo_hidro.v1.json")
        cls.motors = _load("config/motores_inteligencia.v1.json")
        cls.sources = _load("config/fontes_nivon_master.v1.json")

    def test_manifesto_com_escopo_explicito_e_sem_falsa_homologacao(self):
        m = self.manifest
        self.assertEqual(m["schema_version"], "1.0")
        self.assertEqual(m["project"], "NIVON")
        self.assertEqual(m["base_integration_pr"], 13)
        self.assertEqual(m["stack_prs"], [19, 46, 55])
        self.assertEqual(
            m["status"], "CONSOLIDACAO_CODIGO_TESTADO_SINTETICO_NAO_HOMOLOGADO")
        self.assertTrue(m["all_production_gates_must_remain_off"])
        for flag in ("data_independence_proven", "forecast_skill_homologated",
                     "external_vintages_audited", "source_rights_reviewed",
                     "deployment_permitted", "merge_approved"):
            with self.subTest(flag=flag):
                self.assertIs(m[flag], False)

    def test_upstream_original_immutavel_por_blob_git(self):
        originals = self.manifest["upstream_refs"]
        self.assertEqual(len(originals), 6)
        self.assertEqual({x["pr"] for x in originals}, {9, 11})
        for record in originals:
            with self.subTest(path=record["path"]):
                path = ROOT / record["path"]
                self.assertTrue(path.is_file())
                self.assertFalse(path.is_symlink())
                calculated = _git_blob_sha1(path.read_bytes())
                self.assertEqual(calculated, record["git_blob_sha1"])
                self.assertEqual(len(calculated), 40)

    def test_motores_sem_duplicidade_e_entrada_verificavel(self):
        m = self.manifest
        entries = self.motors["engines"]
        by_id = {e["front_id"]: e for e in entries}
        self.assertEqual(len(by_id), len(entries))
        for front, required in m["entrypoints_required"].items():
            with self.subTest(front=front):
                self.assertIn(front, by_id)
                functions = by_id[front]["entrypoints"]
                self.assertEqual(len(functions), len(set(functions)))
                self.assertTrue(set(required).issubset(set(functions)))
                for function in required:
                    module = function.split(":", 1)[0].removeprefix("nivon.")
                    self.assertIn(module, MODULOS)
                    self.assertTrue((ROOT / "src" / "nivon" / (module + ".py")).is_file())

    def test_todos_motores_e_fontes_reais_continuam_off(self):
        m = self.manifest
        for front in self.motors["engines"]:
            for flag in ("scheduled_enabled", "operational_enabled",
                         "inputs_reais_homologados", "previsao_homologada"):
                with self.subTest(front=front["front_id"], flag=flag):
                    self.assertIs(front[flag], False)
        by_id = {x["id"]: x for x in self.sources["datasets"]}
        self.assertEqual(len(by_id), len(self.sources["datasets"]))
        for dataset in m["data_sources_held_off"]:
            with self.subTest(dataset=dataset):
                self.assertIn(dataset, by_id)
                self.assertIs(by_id[dataset]["enabled"], False)
                self.assertIs(by_id[dataset]["collection_authorized"], False)

    def test_analise_merge_nunca_pode_passar_por_forecast_ensemble(self):
        m = self.manifest
        self.assertEqual(m["prohibited_forecast_dataset_ids"], ["CPTEC_MERGE"])
        for x in m["prohibited_forecast_dataset_ids"]:
            self.assertNotIn(x, _PREVISOES)
        self.assertTrue({"NOAA_GFS", "ECMWF_MODELOS"}.issubset(_PREVISOES))

    def test_mjo_de_diagnostico_nao_homologa_modelo_de_chuva(self):
        from nivon.contexto_mjo_asof import (
            indexar_contexto_mjo_asof,
            contextualizar_nwp_com_mjo_asof,
        )
        from nivon.mjo_rmm import normalizar_rmm_bom
        self.assertTrue(callable(indexar_contexto_mjo_asof))
        self.assertTrue(callable(contextualizar_nwp_com_mjo_asof))
        self.assertTrue(callable(normalizar_rmm_bom))


if __name__ == "__main__":
    unittest.main()
