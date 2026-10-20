"""Garante que o catálogo IVO e o delta real permanecem reconciliáveis em CI."""
import unittest
from pathlib import Path
from nivon.pesquisa_tecnologica import auditar


class CatalogoIntegradoTests(unittest.TestCase):
    def test_catalogos_reais_sem_duplicacao_e_sem_auto_instalacao(self):
        raiz = Path(__file__).resolve().parents[1]
        relatorio = auditar(raiz)
        self.assertGreaterEqual(relatorio["base_catalog_items"], 38)
        self.assertEqual(relatorio["research_delta_items"], 4)
        self.assertFalse(relatorio["auto_install_enabled"])
        self.assertEqual(relatorio["total_unique_repositories"], relatorio["base_catalog_items"] + 4)


if __name__ == "__main__":
    unittest.main()
