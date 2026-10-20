import unittest
from nivon.validar_base_cientifica import auditoria_pesquisa


class TestBaseCientifica(unittest.TestCase):
    def test_catalogos_alinhados_e_fechados(self):
        r = auditoria_pesquisa()
        self.assertEqual(r["datasets"], r["rotas"])
        self.assertGreaterEqual(r["historicos_documentados"], 20)
        self.assertGreaterEqual(r["repositorios_inspecionados"], 12)
        self.assertEqual(r["motores_cadastrados"], 28)
        self.assertEqual(r["homologados"], 0)
        self.assertEqual(r["status"], "CADASTRO_CONSISTENTE_NAO_OPERACIONAL")


if __name__ == "__main__":
    unittest.main()
