import copy
import unittest

from nivon.catalogo_fontes import carregar_catalogo, validar_catalogo
from nivon.rotas_coleta import carregar_rotas, validar_rotas

IDS = {
    "NASA_USDA_GLAM_NDVI", "FAO_WAPOR3_EVAPOTRANSPIRACAO",
    "IMF_PORTWATCH_PORT_ACTIVITY", "GEOGLAM_CONDICAO_LAVOURAS",
    "COPERNICUS_C3S_SAZONAL_ENS", "ANTT_PISO_MINIMO_FRETE",
}


class TestCatalogoFontesComplementares(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.cat = carregar_catalogo()
        cls.rotas = carregar_rotas()

    def test_semduplicacao_uma_rota_e_coleta_desativada(self):
        dados = {x["id"]: x for x in self.cat["datasets"]}
        rutas = {x["dataset_id"]: x for x in self.rotas["entries"]}
        self.assertTrue(IDS <= dados.keys())
        self.assertEqual(set(dados), set(rutas))
        self.assertEqual(len(rutas), len(self.rotas["entries"]))
        self.assertEqual(validar_catalogo(self.cat)["coletas_ativadas"], 0)
        self.assertEqual(validar_rotas(self.rotas, self.cat)["coletas_ativadas"], 0)
        for ds in IDS:
            d = dados[ds]; r = rutas[ds]
            self.assertFalse(d["enabled"]); self.assertFalse(d["collection_authorized"])
            self.assertFalse(r["runtime_enabled"]); self.assertFalse(r["scheduled_enabled"])
            self.assertIsNone(r["last_verified_data"])
            self.assertTrue(r["gates_missing"])

    def test_portwatch_antigo_arcgis_nao_e_homologado(self):
        rota = next(x for x in self.rotas["entries"] if x["dataset_id"] == "IMF_PORTWATCH_PORT_ACTIVITY")
        self.assertIn("/api/search/definition/", rota["locator"]["url"])
        self.assertNotIn("services9.arcgis.com", rota["locator"]["url"])
        self.assertIn("MARK_OLD_ARCGIS_LINK_DEPRECATED", rota["gates_missing"])
        self.assertFalse(rota["runtime_enabled"])

    def test_nasa_glam_sem_validacao_de_id_e_mascara_nao_pode_publicar(self):
        rota = next(x for x in self.rotas["entries"] if x["dataset_id"] == "NASA_USDA_GLAM_NDVI")
        self.assertIn("VERIFY_GLAM_ADM_IDS_AND_CROP_MASK", rota["gates_missing"])
        self.assertIn("NASA_GLAM", [x["id"] for x in self.cat["sources"]])
        self.assertFalse(rota["runtime_enabled"])

    def test_antt_piso_nao_e_frete_spot_negociado(self):
        ds = next(x for x in self.cat["datasets"] if x["id"] == "ANTT_PISO_MINIMO_FRETE")
        self.assertIn("piso_legal_nao_frete_mercado", ds["topic"])
        self.assertFalse(ds["enabled"])

    def test_host_estranho_bloqueado(self):
        routes = copy.deepcopy(self.rotas)
        x = next(x for x in routes["entries"] if x["dataset_id"] == "NASA_USDA_GLAM_NDVI")
        x["locator"]["url"] = "https://malicioso.example/api/gettbl/v4"
        with self.assertRaises(ValueError):
            validar_rotas(routes, self.cat)


if __name__ == "__main__":
    unittest.main()
