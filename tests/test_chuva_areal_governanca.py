import unittest
from nivon.catalogo_fontes import carregar_catalogo
from nivon.cobertura import carregar_matriz
from nivon.registro_motores import carregar_registro,validar_registro

class TestChuvaArealGovernance(unittest.TestCase):
    def test_contract_in_all_relevant_fronts_not_operational(self):
        cat=carregar_catalogo();m=carregar_matriz(catalogo=cat)
        reg=carregar_registro();out=validar_registro(reg,m)
        self.assertEqual(out["frentes"],28)
        self.assertEqual(out["modelos_operacionais"],0)
        by={e["front_id"]:e for e in reg["engines"]}
        entry="nivon.chuva_areal_ensemble:agregar_ensemble_chuva_areal"
        for name in ("METEOROLOGIA","HIDROLOGIA","CLIMA_HIDRO"):
            self.assertIn(entry,by[name]["entrypoints"])
            self.assertFalse(by[name]["operational_enabled"])
            self.assertFalse(by[name]["previsao_homologada"])
        met={e["id"]:e for e in m["systems"]}
        self.assertIn("chuva_prevista_areal_bacia_mm_por_intervalo",met["METEOROLOGIA"]["indicators"])
        self.assertIn("chuva_areal_nwp_mm_por_intervalo",met["HIDROLOGIA"]["indicators"])

if __name__=="__main__":
    unittest.main()
