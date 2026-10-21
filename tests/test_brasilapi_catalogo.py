import copy
import unittest

from nivon.catalogo_fontes import carregar_catalogo, validar_catalogo
from nivon.rotas_coleta import carregar_rotas, validar_rotas


class TestBrasilAPIRegistro(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.catalogo = carregar_catalogo()
        cls.rotas = carregar_rotas()

    def test_catalogo_e_rotas_cobrem_novas_fontes(self):
        self.assertEqual(validar_catalogo(self.catalogo)["coletas_ativadas"], 0)
        self.assertEqual(validar_rotas(self.rotas, self.catalogo)["coletas_ativadas"], 0)
        ids = {x["id"] for x in self.catalogo["datasets"]}
        self.assertTrue({"SISCOMEX_TABELA_NCM", "BRASILAPI_NCM_CONSULTA",
                         "BRASILAPI_TAXAS_SEM_DATA"}.issubset(ids))
        self.assertEqual(len(self.catalogo["datasets"]), len(self.rotas["entries"]))

    def test_ncm_oficial_e_primario_brasilapi_apenas_auxiliar(self):
        rows = {d["id"]: d for d in self.catalogo["datasets"]}
        self.assertEqual(rows["SISCOMEX_TABELA_NCM"]["source_id"], "SISCOMEX")
        self.assertEqual(rows["BRASILAPI_NCM_CONSULTA"]["source_id"], "BRASILAPI")
        self.assertEqual(rows["BRASILAPI_NCM_CONSULTA"]["stage"], "CODE_PRESENT")
        self.assertFalse(rows["SISCOMEX_TABELA_NCM"]["enabled"])

    def test_taxas_sem_referencia_nao_sao_fonte_de_indicadores(self):
        route = next(r for r in self.rotas["entries"]
                     if r["dataset_id"] == "BRASILAPI_TAXAS_SEM_DATA")
        self.assertIn("REFERENCE_DATE_MISSING", route["gates_missing"])
        self.assertFalse(route["runtime_enabled"])
        self.assertFalse(route["scheduled_enabled"])
        self.assertIsNone(route["last_verified_data"])

    def test_respeita_proibicao_de_full_scan(self):
        route = next(r for r in self.rotas["entries"]
                     if r["dataset_id"] == "BRASILAPI_NCM_CONSULTA")
        self.assertIn("NO_BULK_SCAN", route["gates_missing"])
        self.assertIn("/api/ncm/v1/33051000", route["locator"]["url"])

    def test_nao_ativar_coleta_por_edicao_acidental(self):
        doc = copy.deepcopy(self.catalogo)
        next(x for x in doc["datasets"] if x["id"] == "BRASILAPI_NCM_CONSULTA")["enabled"] = True
        with self.assertRaises(ValueError):
            validar_catalogo(doc)


if __name__ == "__main__":
    unittest.main()
