"""Integrações reconciliadas em PR #1, sem autorização operacional."""
import unittest
from nivon.catalogo_fontes import carregar_catalogo, validar_catalogo
from nivon.cobertura import carregar_matriz
from nivon.rotas_coleta import carregar_rotas, validar_rotas
from nivon.registro_motores import carregar_registro, validar_registro
from nivon.lineup_nacional import carregar_escopo, produto_canonico

class TestIntegracaoConvergente(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.cat=carregar_catalogo()
        cls.m=carregar_matriz(catalogo=cls.cat)
        cls.rotas=carregar_rotas()
        cls.reg=carregar_registro()
        cls.escopo=carregar_escopo()

    def test_45_registros_nacionais_todos_canonicos(self):
        ports={x["id"] for x in self.escopo["ports"]}
        datas={x["id"].removeprefix("LINEUP_") for x in self.cat["datasets"] if x["id"].startswith("LINEUP_")}
        self.assertEqual(len(ports),45)
        self.assertEqual(datas,ports)
        self.assertTrue(all(not x["live_enabled"] for x in self.escopo["ports"]))

    def test_130_datasets_rotas_e_96_fontes_sem_execucao(self):
        meta=validar_catalogo(self.cat)
        self.assertEqual(meta["datasets"],130)
        self.assertEqual(meta["fontes"],96)
        self.assertEqual(meta["portos_br"],45)
        self.assertEqual(validar_rotas(self.rotas,self.cat)["rotas"],130)
        self.assertTrue(all(not d["enabled"] for d in self.cat["datasets"]))
        self.assertTrue(all(not r["runtime_enabled"] and not r["scheduled_enabled"] for r in self.rotas["entries"]))

    def test_maritimo_usa_todos_os_45_lineups(self):
        mar=next(x for x in self.m["systems"] if x["id"]=="MARITIMO")
        self.assertEqual(len([x for x in mar["data"] if x.startswith("LINEUP_")]),45)

    def test_ppi_nao_equivale_preco_revenda(self):
        ppi=next(x for x in self.cat["datasets"] if x["id"]=="ANP_PPI_COMBUSTIVEIS")
        self.assertFalse(ppi["collection_authorized"])
        self.assertIn("PPI",ppi["id"])
        self.assertNotEqual(ppi["id"],"ANP_PRECO_REVENDA_DIESEL")

    def test_alias_suino_e_gergelim_conciliados(self):
        self.assertEqual(produto_canonico("SUINOS"),"SUINO")
        self.assertEqual(produto_canonico("CARNE SUINA"),"SUINO")
        self.assertEqual(produto_canonico("GERGELIM"),"GERGELIM")

    def test_motores_importados_sem_promocao_indevida(self):
        r=validar_registro(self.reg,self.m)
        self.assertEqual(r["frentes"],28)
        self.assertEqual(r["modelos_operacionais"],0)
        self.assertGreaterEqual(r["funcoes_vinculadas"],100)
        m={x["front_id"]:x for x in self.reg["engines"]}
        self.assertIn("nivon.lineup_nacional:consolidar",m["MARITIMO"]["entrypoints"])
        self.assertIn("nivon.conab_agrobr:normalizar_progresso",m["SOJA"]["entrypoints"])
        self.assertIn("nivon.briefing_composto:montar_briefing",m["BRIEFING_DIARIO"]["entrypoints"])
        self.assertIn("nivon.previsoes_bibliotecas:backtest_mensal",m["MILHO"]["entrypoints"])

if __name__=="__main__":
    unittest.main()
