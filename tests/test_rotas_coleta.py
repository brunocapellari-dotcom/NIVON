import copy
import unittest

from nivon.catalogo_fontes import carregar_catalogo
from nivon.rotas_coleta import (
    ErroRota, carregar_rotas, montar_plano, validar_rotas,
)


class TestRotasColetores(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.catalogo = carregar_catalogo()
        cls.rotas = carregar_rotas()

    def test_cobre_todos_86_datasets_sem_duplicatas(self):
        d = validar_rotas(self.rotas, self.catalogo)
        self.assertEqual(d["fontes"], 59)
        self.assertEqual(d["datasets"], 86)
        self.assertEqual(d["rotas"], 86)

    def test_armazens_e_municipios_estao_canonicos(self):
        ids = {e["dataset_id"] for e in self.rotas["entries"]}
        self.assertIn("CONAB_ARMAZENS_CAPACIDADE", ids)
        self.assertIn("IBGE_CODIGOS_MUNICIPIOS", ids)
        self.assertIn("UNEM_BIORREFINARIAS", ids)
        self.assertIn("EPE_BEN_SERIES_HISTORICAS", ids)

    def test_risco_nao_foi_transformado_em_coleta(self):
        d = validar_rotas(self.rotas, self.catalogo)
        self.assertEqual(d["coletas_ativadas"], 0)
        self.assertFalse(any(e["runtime_enabled"] or e["scheduled_enabled"]
                             for e in self.rotas["entries"]))

    def test_plano_diesel_inclui_revenda_e_paridade_futura(self):
        ids = {x["dataset"] for x in montar_plano(
            self.rotas, self.catalogo, prioridade="P0", grupo="ENERGIA")}
        self.assertIn("ANP_PRECO_REVENDA_DIESEL", ids)
        self.assertIn("ANP_IMPORTACAO_DIESEL", ids)

    def test_antt_mdfe_marcado_como_painel_nao_api(self):
        m = next(e for e in self.rotas["entries"]
                 if e["dataset_id"] == "ANTT_MDFE_RODOVIARIO")
        self.assertEqual(m["collector_class"], "DASHBOARD_MANUAL_EXPORT")
        self.assertEqual(m["locator"]["kind"], "OFFICIAL_DASHBOARD")
        self.assertFalse(m["scheduled_enabled"])

    def test_unidade_mapa_tem_url_csv_especifica(self):
        m = next(e for e in self.rotas["entries"]
                 if e["dataset_id"] == "MAPA_SIPEAGRO_RACAO")
        self.assertEqual(m["locator"]["kind"], "DIRECT_PUBLIC_FILE")
        self.assertTrue(m["locator"]["url"].endswith(".csv"))

    def test_fonte_paga_nao_pode_ativar(self):
        doc = copy.deepcopy(self.rotas)
        m = next(e for e in doc["entries"] if e["dataset_id"] == "CME_FUTUROS")
        m["scheduled_enabled"] = True
        with self.assertRaises(ErroRota):
            validar_rotas(doc, self.catalogo)

    def test_host_nao_permitido_bloqueado(self):
        doc = copy.deepcopy(self.rotas)
        m = next(e for e in doc["entries"] if e["dataset_id"] == "BCB_PTAX")
        m["locator"]["url"] = "https://malicioso.example/api"
        with self.assertRaises(ErroRota):
            validar_rotas(doc, self.catalogo)

    def test_dataset_excluido_bloqueia_catalogo(self):
        doc = copy.deepcopy(self.rotas)
        doc["entries"].pop()
        with self.assertRaises(ErroRota):
            validar_rotas(doc, self.catalogo)

    def test_sem_gates_de_persistencia_e_backfill_nao_e_operavel(self):
        doc = copy.deepcopy(self.rotas)
        doc["entries"][0]["gates_missing"] = ["VERIFY_COLLECTION_RIGHTS"]
        with self.assertRaises(ErroRota):
            validar_rotas(doc, self.catalogo)

    def test_nao_inferir_endpoint_inexistente(self):
        doc = copy.deepcopy(self.rotas)
        e = next(e for e in doc["entries"] if e["dataset_id"] == "IBGE_PAM")
        self.assertIsNone(e["locator"]["url"])
        e["locator"]["kind"] = "DIRECT_PUBLIC_FILE"
        with self.assertRaises(ErroRota):
            validar_rotas(doc, self.catalogo)

    def test_urls_sem_credenciais(self):
        doc = copy.deepcopy(self.rotas)
        m = next(e for e in doc["entries"] if e["dataset_id"] == "BCB_PTAX")
        m["locator"]["url"] = "https://admin:senha@olinda.bcb.gov.br/api"
        with self.assertRaises(ErroRota):
            validar_rotas(doc, self.catalogo)

    def test_amplitude_todas_as_areas(self):
        plano = montar_plano(self.rotas, self.catalogo)
        grupos = {x["grupo"] for x in plano}
        self.assertGreaterEqual(len(grupos), 15)
        self.assertEqual(len(plano), 86)


if __name__ == "__main__":
    unittest.main()
