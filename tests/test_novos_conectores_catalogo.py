"""Cobertura de contratos novos sem promover coletores automaticamente."""
import unittest
from nivon.catalogo_fontes import carregar_catalogo, validar_catalogo
from nivon.rotas_coleta import carregar_rotas, validar_rotas

CODIGO_NOVO = {
    "USDA_AMS_GTR_FRETE_MULTIMODAL": "nivon.planilhas_publicas_xlsx.consultar_planilha",
    "USDA_AMS_GTR_PRECO_BASIS_EXPORT": "nivon.planilhas_publicas_xlsx.consultar_planilha",
    "WB_PINK_SHEET_COMMODITIES": "nivon.planilhas_publicas_xlsx.consultar_planilha",
    "NOAA_ENSO_INDICES_HISTORICOS": "nivon.noaa_mei_v2.consultar_mei_v2",
    "ESA_WORLDCOVER_2021_10M": "nivon.georaster_catalogos.consultar_esa_tile",
    "JRC_GSW_AGUA_SUPERFICIAL": "nivon.georaster_catalogos.consultar_jrc_wmts",
    "EARTH_SEARCH_STAC_CENAS": "nivon.earth_search_stac.consultar_cenas",
}


class TestNovosConectoresNoCatalogo(unittest.TestCase):
    def test_uma_rota_sem_agenda_por_dataset(self):
        doc = carregar_catalogo()
        r = carregar_rotas()
        self.assertEqual(validar_catalogo(doc)["coletas_ativadas"], 0)
        self.assertEqual(validar_rotas(r, doc)["coletas_ativadas"], 0)
        self.assertEqual(len(doc["datasets"]), len(r["entries"]))
        self.assertEqual(len({x["dataset_id"] for x in r["entries"]}), len(r["entries"]))
        d = {x["id"]: x for x in doc["datasets"]}
        routes = {x["dataset_id"]: x for x in r["entries"]}
        for id_, code in CODIGO_NOVO.items():
            with self.subTest(dataset=id_):
                self.assertEqual(d[id_]["stage"], "CODE_PRESENT")
                self.assertEqual(d[id_]["existing_module"], code)
                self.assertFalse(d[id_]["enabled"])
                self.assertFalse(routes[id_]["runtime_enabled"])
                self.assertFalse(routes[id_]["scheduled_enabled"])
                self.assertIsNone(routes[id_]["last_verified_data"])
                self.assertIn("REAL_PRODUCTION_RESPONSE_SMOKE", routes[id_]["gates_missing"])
                self.assertIn("DURABLE_PERSISTENCE_AND_RESTORE", routes[id_]["gates_missing"])

    def test_nao_tratar_metadados_como_imagem_ou_frete_real(self):
        d = {x["id"]: x for x in carregar_catalogo()["datasets"]}
        self.assertIn("frete_rodoviario", d["USDA_AMS_GTR_FRETE_MULTIMODAL"]["topic"])
        self.assertTrue(d["ESA_WORLDCOVER_2021_10M"]["topic"].find("2021") != -1)


if __name__ == "__main__":
    unittest.main()
