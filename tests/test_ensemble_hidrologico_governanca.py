import unittest
from nivon.catalogo_fontes import carregar_catalogo
from nivon.cobertura import carregar_matriz
from nivon.registro_motores import carregar_registro,validar_registro

class TestEnsembleHydrologyRegistration(unittest.TestCase):
    def test_new_ensemble_registered_but_never_operational(self):
        c=carregar_catalogo()
        m=carregar_matriz(catalogo=c)
        e=carregar_registro()
        status=validar_registro(e,m)
        self.assertEqual(status["frentes"],28)
        self.assertEqual(status["modelos_operacionais"],0)
        by={x["front_id"]:x for x in e["engines"]}
        path="nivon.ensemble_hidrologico_bacia:cenario_ensemble_bacia"
        self.assertIn(path,by["HIDROLOGIA"]["entrypoints"])
        self.assertIn(path,by["CLIMA_HIDRO"]["entrypoints"])
        self.assertFalse(by["HIDROLOGIA"]["operational_enabled"])
        self.assertFalse(by["HIDROLOGIA"]["previsao_homologada"])
        bymat={x["id"]:x for x in m["systems"]}
        self.assertIn("fracao_ensemble_acima_limiar_condicional",bymat["HIDROLOGIA"]["indicators"])
        self.assertEqual(len(bymat["HIDROLOGIA"]["indicators"]),by["HIDROLOGIA"]["indicators_planned"])

if __name__=="__main__":
    unittest.main()
