import unittest
from nivon.catalogo_fontes import carregar_catalogo
from nivon.cobertura import carregar_matriz
from nivon.registro_motores import carregar_registro,validar_registro

class TestHydrometGovernance(unittest.TestCase):
    def test_motores_matematicos_nao_se_passam_por_geracao_operacional(self):
        cat=carregar_catalogo();mat=carregar_matriz(catalogo=cat)
        engines=carregar_registro();result=validar_registro(engines,mat)
        self.assertEqual(result["frentes"],28)
        self.assertEqual(result["modelos_operacionais"],0)
        e={x["front_id"]:x for x in engines["engines"]}
        for front in ("METEOROLOGIA","HIDROLOGIA","CLIMA_HIDRO"):
            self.assertFalse(e[front]["operational_enabled"])
            self.assertFalse(e[front]["previsao_homologada"])
        self.assertIn("nivon.meteorologia_probabilistica:avaliar_ensemble",e["METEOROLOGIA"]["entrypoints"])
        self.assertIn("nivon.hidrograma_bacia:hidrograma_evento_cn",e["HIDROLOGIA"]["entrypoints"])
        self.assertIn("nivon.calibracao_cn_bacias:calibrar_cn_historico",e["HIDROLOGIA"]["entrypoints"])
        m={x["id"]:x for x in mat["systems"]}
        self.assertIn("crps_ensemble",m["METEOROLOGIA"]["indicators"])
        self.assertIn("skill_cn_holdout_baseline",m["HIDROLOGIA"]["indicators"])
        self.assertEqual(e["HIDROLOGIA"]["indicators_planned"],len(m["HIDROLOGIA"]["indicators"]))
if __name__=="__main__":unittest.main()
