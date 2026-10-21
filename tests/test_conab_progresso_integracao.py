import unittest
from nivon.catalogo_fontes import carregar_catalogo
from nivon.rotas_coleta import carregar_rotas, validar_rotas
from nivon.cobertura import carregar_matriz
from nivon.registro_motores import carregar_registro, validar_registro

class TestConabProgressoNaMatriz(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.cat=carregar_catalogo()
        cls.mat=carregar_matriz(catalogo=cls.cat)
        cls.routes=carregar_rotas()
        cls.eng=carregar_registro()

    def test_plantio_e_colheita_ligados_a_quatro_culturas(self):
        self.assertEqual(validar_rotas(self.routes,self.cat)["rotas"],len(self.cat["datasets"]))
        self.assertGreaterEqual(len(self.cat["sources"]),100)
        v=validar_registro(self.eng,self.mat)
        self.assertEqual(v["frentes"],28)
        for front in ("SOJA","MILHO","ALGODAO","TRIGO"):
            s=next(x for x in self.mat["systems"] if x["id"]==front)
            self.assertIn("CONAB_PROGRESSO_SEMANAL",s["data"])
            self.assertIn("semeadura_semanal_percentual",s["indicators"])
            self.assertIn("colheita_semanal_percentual",s["indicators"])

    def test_fontes_nao_atuam_automaticamente(self):
        d=next(x for x in self.cat["datasets"] if x["id"]=="CONAB_PROGRESSO_SEMANAL")
        r=next(x for x in self.routes["entries"] if x["dataset_id"]==d["id"])
        self.assertEqual(d["stage"],"CODE_PRESENT")
        self.assertFalse(d["collection_authorized"])
        self.assertFalse(d["enabled"])
        self.assertFalse(r["runtime_enabled"])
        self.assertFalse(r["scheduled_enabled"])
        self.assertIn("ARROZ",d["products"])
        self.assertIn("FEIJAO",d["products"])

if __name__=="__main__":
    unittest.main()
