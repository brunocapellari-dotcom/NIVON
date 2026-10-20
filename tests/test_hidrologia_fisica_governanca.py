import unittest
from nivon.catalogo_fontes import carregar_catalogo
from nivon.cobertura import carregar_matriz
from nivon.registro_motores import carregar_registro,validar_registro

class TestMotoresHidrologicosFisicosGovernados(unittest.TestCase):
    def test_scscn_e_muskingum_registrados_sem_promover(self):
        c=carregar_catalogo();m=carregar_matriz(catalogo=c);e=carregar_registro()
        result=validar_registro(e,m)
        self.assertEqual(result["frentes"],28)
        self.assertEqual(result["modelos_operacionais"],0)
        h=next(x for x in e["engines"] if x["front_id"]=="HIDROLOGIA")
        self.assertIn("nivon.hidrologia_chuva_vazao:escoamento_scs_cn",h["entrypoints"])
        self.assertIn("nivon.hidrologia_chuva_vazao:propagar_muskingum",h["entrypoints"])
        self.assertFalse(h["previsao_homologada"])
        frente=next(x for x in m["systems"] if x["id"]=="HIDROLOGIA")
        self.assertIn("erro_balanco_trecho_muskingum_m3",frente["indicators"])
        self.assertIn("ANA_HIDRO",frente["data"])
if __name__=="__main__":unittest.main()
