"""Fixtures sinteticas de line-up, sem dependencia de terceiros."""
import unittest
from nivon.lineup_portos import FONTES, extrair_lineup_html, verificar_cdp, importar_gpv_csv, inferir_presenca_amaggi

class TestLineupPortos(unittest.TestCase):
    def test_registry(self):
        self.assertTrue({"suape", "imbituba", "ponta_madeira", "santarem_cdp",
                         "vila_conde_cdp", "itacoatiara_publico", "itacoatiara_amaggi"} <= set(FONTES))

    def test_imbituba_programado_nao_realizado(self):
        html = "<h3>Programacao</h3><table><tr><th>Navio</th><th>Situacao</th><th>Berco</th><th>Carga</th><th>Toneladas</th></tr><tr><td>SHIP TEST</td><td>Esperado</td><td>1</td><td>Soja</td><td>1000</td></tr></table>"
        rows = extrair_lineup_html(html, "imbituba", coletado_em="2026-10-22T22:00:00Z")
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["status"], "ESPERADO_PROGRAMADO")
        self.assertFalse(rows[0]["realizado_confirmado"])

    def test_cdp_stale_flag(self):
        entries = [{"data_referencia": "01/01/2022"}]
        self.assertIn("PROGRAMACAO_DESATUALIZADA", verificar_cdp(entries, corte="2026-10-22")["flags"])

    def test_gpv_requer_autorizacao(self):
        with self.assertRaises(PermissionError):
            importar_gpv_csv("Navio\nSHIP TEST", acesso_autorizado=False,
                             coletado_em="2026-10-22T22:00:00Z")

    def test_ais_sem_inventar_carga(self):
        polygon = [(0,0), (0,1), (1,1), (1,0)]
        events = [{"imo":"1234567", "latitude":0.5, "longitude":0.5,
                   "timestamp":f"2026-10-22T{h:02d}:00:00Z"} for h in (12,13,14)]
        rows = inferir_presenca_amaggi(events, geocerca_terminal=polygon)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["natureza"], "INFERIDO_AIS")
        self.assertIsNone(rows[0]["produto_informado"])
        self.assertFalse(rows[0]["realizado_confirmado"])

    def test_imbituba_atracado_nao_vira_esperado(self):
        html = "<h3>Programacao de Navios</h3><table><tr><th>Navio</th><th>Situacao</th><th>Berco</th></tr><tr><td>TEST SHIP</td><td>Atracado</td><td>2</td></tr></table>"
        rows = extrair_lineup_html(html, "imbituba", coletado_em="2026-10-22T22:00:00Z")
        self.assertEqual(rows[0]["status"], "ATRACADO_INFORMADO")

if __name__ == "__main__":
    unittest.main()
