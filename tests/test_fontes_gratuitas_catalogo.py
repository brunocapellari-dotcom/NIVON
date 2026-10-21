import copy
import unittest

from nivon.catalogo_fontes import carregar_catalogo, validar_catalogo
from nivon.rotas_coleta import carregar_rotas, validar_rotas


IDS = {
    "OPEN_METEO_PREVISAO_DIARIA",
    "OPEN_METEO_HISTORICO_REANALISE",
    "INPE_QUEIMADAS_FOCOS_CSV",
    "INPE_QUEIMADAS_RISCO_FOGO",
    "INPE_TERRABRASILIS_PRODES_WFS",
    "DADOS_GOV_BR_CATALOGO_API",
    "WB_INDICADORES_MACRO_BR",
    "BCB_SGS_TAXA_SELIC_DIARIA",
}


class TestFontesGratuitasCatalogadas(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.catalogo = carregar_catalogo()
        cls.rotas = carregar_rotas()

    def test_novos_datasets_uma_rota_para_cada(self):
        fontes = {d["id"]: d for d in self.catalogo["datasets"]}
        routes = {r["dataset_id"]: r for r in self.rotas["entries"]}
        self.assertTrue(IDS <= fontes.keys())
        self.assertEqual(set(fontes), set(routes))
        self.assertEqual(len(routes), len(self.rotas["entries"]))
        self.assertEqual(validar_catalogo(self.catalogo)["coletas_ativadas"], 0)
        self.assertEqual(validar_rotas(self.rotas, self.catalogo)["coletas_ativadas"], 0)

    def test_zero_ativacoes_e_datas_obrigatorias(self):
        sources = {s["id"]: s for s in self.catalogo["sources"]}
        for row in self.catalogo["datasets"]:
            if row["id"] not in IDS:
                continue
            self.assertFalse(row["enabled"])
            self.assertFalse(row["collection_authorized"])
            self.assertFalse(row["commercial_redistribution_authorized"])
            self.assertEqual(row["data_dates_required"],
                             ["competencia", "referencia", "publicacao", "coleta"])
            self.assertIn(row["source_id"], sources)
        for route in self.rotas["entries"]:
            if route["dataset_id"] in IDS:
                self.assertFalse(route["runtime_enabled"])
                self.assertFalse(route["scheduled_enabled"])
                self.assertIsNone(route["last_verified_data"])

    def test_gratuito_nao_e_homologado(self):
        rows = {r["dataset_id"]: r for r in self.rotas["entries"]}
        self.assertIn("CC_BY_ATTRIBUTION",
                      rows["OPEN_METEO_PREVISAO_DIARIA"]["gates_missing"])
        self.assertIn("REANALYSIS_NOT_OBSERVED",
                      rows["OPEN_METEO_HISTORICO_REANALISE"]["gates_missing"])
        self.assertIn("SATELLITE_DEDUP_AND_COVERAGE",
                      rows["INPE_QUEIMADAS_FOCOS_CSV"]["gates_missing"])
        self.assertIn("DO_NOT_USE_RESTRICTED_EARLY_DETER",
                      rows["INPE_TERRABRASILIS_PRODES_WFS"]["gates_missing"])

    def test_hosts_externos_nao_podem_ser_substituidos(self):
        for id_ in ("OPEN_METEO_PREVISAO_DIARIA", "BCB_SGS_TAXA_SELIC_DIARIA",
                    "INPE_TERRABRASILIS_PRODES_WFS", "WB_INDICADORES_MACRO_BR"):
            rotas = copy.deepcopy(self.rotas)
            row = next(r for r in rotas["entries"] if r["dataset_id"] == id_)
            row["locator"]["url"] = "https://coleta-maliciosa.example/obter"
            with self.subTest(id_=id_), self.assertRaises(ValueError):
                validar_rotas(rotas, self.catalogo)

    def test_chave_usda_exigida_sem_segredo(self):
        routes = {r["dataset_id"]: r for r in self.rotas["entries"]}
        for id_ in ("USDA_PSD", "USDA_EXPORT_SALES"):
            r = routes[id_]
            self.assertEqual(r["authentication"], "FREE_API_DATA_GOV_KEY_REQUIRED")
            self.assertIn("FREE_API_KEY_PRIVATE_STORAGE", r["gates_missing"])
            self.assertFalse(r["runtime_enabled"])

    def test_cftc_continua_distinta_de_cbot_preco(self):
        r = next(x for x in self.rotas["entries"] if x["dataset_id"] == "CFTC_COT_WEEKLY")
        self.assertIn("não cotação CBOT", r["source_note"])
        self.assertFalse(r["runtime_enabled"])

    def test_selic_diaria_codigo_existente_sem_coleta(self):
        d = next(x for x in self.catalogo["datasets"]
                 if x["id"] == "BCB_SGS_TAXA_SELIC_DIARIA")
        self.assertEqual(d["stage"], "CODE_PRESENT")
        self.assertEqual(d["existing_module"], "nivon.bcb_sgs_selic.normalizar_selic_diaria")


if __name__ == "__main__":
    unittest.main()
