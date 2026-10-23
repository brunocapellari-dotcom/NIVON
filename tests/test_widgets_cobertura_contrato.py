"""Gates offline da cobertura dos 42 widgets.

Não consulta Neon/Google Cloud, não coleta os widgets e não contém preços.
A homologação SQL real é feita separadamente no Neon.
"""
import re
import unittest
from pathlib import Path

from nivon.cotacoes import carregar_catalogo

ROOT = Path(__file__).resolve().parents[1]
COBERTURA = (ROOT / "database/neon_widgets_cobertura_42.sql").read_text(encoding="utf-8")


class TestCoberturaWidgets(unittest.TestCase):
    def test_todos_ids_catalogados_uma_unica_vez(self):
        trecho = COBERTURA.split("WITH catalogo(", 1)[1].split("),\nfontes_verificadas AS", 1)[0]
        ids = [int(v) for v in re.findall(r"\(\s*(\d+),'(?:algodao|bovinos|cafe|financeiro|milho|soja|sucroenergetico)'", trecho)]
        catalogados = {item["id"] for item in carregar_catalogo()["indicadores"]}
        self.assertEqual(len(ids), 42)
        self.assertEqual(len(set(ids)), 42)
        self.assertEqual(set(ids), catalogados)

    def test_imea_nao_promove_publicacao_como_referencia(self):
        self.assertIn("AND s.reference_date IS NULL", COBERTURA)
        self.assertIn("FALSE AS elegivel_tendencia_diaria", COBERTURA)
        self.assertIn("'PUBLICACAO_SEM_REFERENCIA'", COBERTURA)
        self.assertNotIn("COALESCE(s.reference_date,s.published_at", COBERTURA)
        self.assertNotIn("s.published_at::date AS data_referencia", COBERTURA)

    def test_imea_so_duas_series_preco_fisico(self):
        self.assertIn("s.indicator_kind='PRECO'", COBERTURA)
        self.assertIn("s.unit='R$/sc'", COBERTURA)
        self.assertIn("s.indicator_id='708192508838936580'", COBERTURA)
        self.assertIn("s.indicator_id='708192508838936581'", COBERTURA)
        self.assertIn("s.indicator_name='Preço soja disponível compra'", COBERTURA)
        self.assertIn("s.indicator_name='Preço milho disponível compra'", COBERTURA)
        self.assertIn("s.price > 0", COBERTURA)

    def test_sem_coleta_direta_de_widget_ou_claim_gcp(self):
        self.assertIn("FALSE::boolean AS widget_coletado_diretamente", COBERTURA)
        self.assertIn("FALSE::boolean AS google_cloud_carga_comprovada", COBERTURA)
        self.assertNotIn("noticiasagricolas.com.br/widgets/cotacoes?", COBERTURA)

    def test_source_view_separada_de_cotacoes_imea(self):
        self.assertIn("public.nivon_widgets_origens_verificadas_v", COBERTURA)
        self.assertIn("public.nivon_widgets_imea_publicacoes_v", COBERTURA)
        self.assertIn("CATALOGADO_SEM_DADO_PRIMARIO_VINCULADO", COBERTURA)
        self.assertIn("IMEA_PUBLICACAO_SEM_DATA_REFERENCIA", COBERTURA)


if __name__ == "__main__":
    unittest.main()
