import copy
import unittest

from nivon.catalogo_fontes import carregar_catalogo, validar_catalogo
from nivon.rotas_coleta import carregar_rotas, validar_rotas


class TestRegistroSISFOGO(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.catalogo = carregar_catalogo()
        cls.rotas = carregar_rotas()

    def test_uma_fonte_uma_rota_e_todos_controles_off(self):
        ids = [r["dataset_id"] for r in self.rotas["entries"]]
        self.assertEqual(ids.count("IBAMA_SISFOGO_ROI_FINALIZADOS"), 1)
        self.assertEqual(len(ids), len(self.catalogo["datasets"]))
        self.assertEqual(validar_catalogo(self.catalogo)["coletas_ativadas"], 0)
        self.assertEqual(validar_rotas(self.rotas, self.catalogo)["coletas_ativadas"], 0)

    def test_url_producao_sem_homologacao_ou_proxy_de_dev(self):
        fonte = next(x for x in self.catalogo["sources"] if x["id"] == "IBAMA_SISFOGO")
        rota = next(x for x in self.rotas["entries"]
                    if x["dataset_id"] == "IBAMA_SISFOGO_ROI_FINALIZADOS")
        self.assertEqual(fonte["official_url"], "https://sisfogo.sistema.gov.br/api/v1/roi/publico")
        self.assertTrue(rota["locator"]["url"].startswith(fonte["official_url"]))
        self.assertFalse(rota["runtime_enabled"])
        self.assertFalse(rota["scheduled_enabled"])
        self.assertIsNone(rota["last_verified_data"])
        self.assertNotIn(".hom.", rota["locator"]["url"])
        self.assertIn("LIVE_SAMPLE_AND_OPERATION_RIGHTS_NOT_VALIDATED", rota["primary_blocker"])
        self.assertIn("PAGINATION_STABILITY_AND_RETIFICATION_AUDIT", rota["gates_missing"])

    def test_nao_declarar_ativacao_sem_homologacao(self):
        catalogo = copy.deepcopy(self.catalogo)
        next(x for x in catalogo["datasets"]
             if x["id"] == "IBAMA_SISFOGO_ROI_FINALIZADOS")["collection_authorized"] = True
        with self.assertRaises(ValueError):
            validar_catalogo(catalogo)
        rotas = copy.deepcopy(self.rotas)
        next(x for x in rotas["entries"]
             if x["dataset_id"] == "IBAMA_SISFOGO_ROI_FINALIZADOS")["runtime_enabled"] = True
        with self.assertRaises(ValueError):
            validar_rotas(rotas, self.catalogo)


if __name__ == "__main__":
    unittest.main()
