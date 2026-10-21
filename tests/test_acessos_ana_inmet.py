import unittest
from nivon.registro_motores import carregar_registro,validar_registro
from nivon.cobertura import carregar_matriz
from nivon.catalogo_fontes import carregar_catalogo
from nivon.ana_hidrowebservice import SessaoANA

class TestContratosPrivados(unittest.TestCase):
    def test_credenciais_nao_aparecem_em_repr(self):
        sess=SessaoANA(token="T"*100,emitido_monotonic=0)
        self.assertNotIn("T"*100,repr(sess))

    def test_hidrologia_e_meteorologia_registradas(self):
        cat=carregar_catalogo()
        mat=carregar_matriz(catalogo=cat)
        reg=carregar_registro()
        self.assertEqual(validar_registro(reg,mat)["frentes"],28)
        by={r["front_id"]:r for r in reg["engines"]}
        self.assertIn("nivon.ana_hidrowebservice:normalizar_adotada",by["HIDROLOGIA"]["entrypoints"])
        self.assertIn("nivon.inmet_bdmep:receber_bdmep",by["METEOROLOGIA"]["entrypoints"])
        self.assertFalse(by["HIDROLOGIA"]["operational_enabled"])
        self.assertFalse(by["METEOROLOGIA"]["operational_enabled"])

if __name__=="__main__":unittest.main()
