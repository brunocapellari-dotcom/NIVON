"""Governança Earth Search, USDA GTR, JRC, ESA, NOAA ENSO, World Bank."""
import copy
import unittest
from nivon.catalogo_fontes import carregar_catalogo, validar_catalogo
from nivon.rotas_coleta import carregar_rotas, validar_rotas

IDS = {"EARTH_SEARCH_STAC_CENAS", "ESA_WORLDCOVER_2021_10M",
       "JRC_GSW_AGUA_SUPERFICIAL", "USDA_AMS_GTR_FRETE_MULTIMODAL",
       "USDA_AMS_GTR_PRECO_BASIS_EXPORT", "NOAA_ENSO_INDICES_HISTORICOS",
       "WB_PINK_SHEET_COMMODITIES"}


class TestDatasetsDescobertos(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.cat = carregar_catalogo()
        cls.rot = carregar_rotas()

    def test_novo_conjunto_possui_uma_rota_por_dataset_e_sem_ativacao(self):
        d = {x["id"]: x for x in self.cat["datasets"]}
        r = {x["dataset_id"]: x for x in self.rot["entries"]}
        self.assertTrue(IDS <= set(d))
        self.assertEqual(set(d), set(r))
        self.assertEqual(len(r), len(self.rot["entries"]))
        self.assertEqual(validar_catalogo(self.cat)["coletas_ativadas"], 0)
        self.assertEqual(validar_rotas(self.rot, self.cat)["coletas_ativadas"], 0)
        for ident in IDS:
            self.assertFalse(d[ident]["enabled"])
            self.assertFalse(d[ident]["collection_authorized"])
            self.assertFalse(r[ident]["runtime_enabled"])
            self.assertFalse(r[ident]["scheduled_enabled"])
            self.assertIsNone(r[ident]["last_verified_data"])
            self.assertIn("HISTORICAL_BACKFILL", r[ident]["gates_missing"])

    def test_usda_gtr_reaproveita_a_fonte_sem_chave_fas(self):
        d = {x["id"]: x for x in self.cat["datasets"]}
        r = {x["dataset_id"]: x for x in self.rot["entries"]}
        for ident in ("USDA_AMS_GTR_FRETE_MULTIMODAL", "USDA_AMS_GTR_PRECO_BASIS_EXPORT"):
            self.assertEqual(d[ident]["source_id"], "USDA")
            self.assertEqual(r[ident]["authentication"], "NONE_EXPECTED_VERIFY")
            self.assertTrue(r[ident]["locator"]["url"].endswith(".xlsx"))
        self.assertIn("US_PROXY_NOT_BRAZIL_FREIGHT", r["USDA_AMS_GTR_FRETE_MULTIMODAL"]["gates_missing"])

    def test_worldcover_snapshot_2021_nao_2026(self):
        r = next(x for x in self.rot["entries"] if x["dataset_id"] == "ESA_WORLDCOVER_2021_10M")
        self.assertIn("2021_STATIC_NOT_2026", r["gates_missing"])
        self.assertEqual(r["locator"]["kind"], "DIRECT_PUBLIC_FILE")

    def test_jrc_versions_and_water_not_discharge(self):
        r = next(x for x in self.rot["entries"] if x["dataset_id"] == "JRC_GSW_AGUA_SUPERFICIAL")
        self.assertIn("BACKFILL_V14_PLUS_V15_MERGE", r["gates_missing"])
        self.assertIn("MONTHLY_RECURRENCE_BUG_KNOWN", r["gates_missing"])

    def test_url_spoofing_bloqueado(self):
        rot = copy.deepcopy(self.rot)
        r = next(x for x in rot["entries"] if x["dataset_id"] == "EARTH_SEARCH_STAC_CENAS")
        r["locator"]["url"] = "https://malicious.invalid/v1/search"
        with self.assertRaises(ValueError):
            validar_rotas(rot, self.cat)


if __name__ == "__main__":
    unittest.main()
