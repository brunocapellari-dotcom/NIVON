import unittest
from nivon.catalogo_fontes import carregar_catalogo,validar_catalogo
from nivon.cobertura import carregar_matriz
from nivon.registro_motores import carregar_registro,validar_registro
from nivon.rotas_coleta import carregar_rotas,validar_rotas

class TestPipelineClimaGovernado(unittest.TestCase):
    def test_motores_conectados_sem_ativacao(self):
        c=carregar_catalogo();mat=carregar_matriz(catalogo=c)
        m=carregar_registro();result=validar_registro(m,mat)
        self.assertEqual(result["frentes"],28)
        ids={x["front_id"]:x for x in m["engines"]}
        self.assertIn("nivon.nasa_power_captura_manual:capturar_power_manual",ids["METEOROLOGIA"]["entrypoints"])
        self.assertIn("nivon.chirps_v3_conservacao:reconciliar_chirps_pentada",ids["HIDROLOGIA"]["entrypoints"])
        self.assertFalse(ids["METEOROLOGIA"]["operational_enabled"])
    def test_fonte_chirps_licenca_com_atribuicao_pendente(self):
        c=carregar_catalogo();meta=validar_catalogo(c)
        self.assertEqual(meta["datasets"],135)
        source=next(x for x in c["sources"] if x["id"]=="UCSB_CHC")
        self.assertEqual(source["rights"],"ATTRIBUTION_REVIEW")
        ds=next(x for x in c["datasets"] if x["id"]=="CHIRPS_V3_CHUVA")
        self.assertIn("CC BY 4.0",ds["notes"])
        self.assertFalse(ds["enabled"])
        routes=carregar_rotas()
        self.assertEqual(validar_rotas(routes,c)["rotas"],135)
        self.assertTrue(all(not r["runtime_enabled"] and not r["scheduled_enabled"] for r in routes["entries"]))
if __name__=="__main__":
    unittest.main()
