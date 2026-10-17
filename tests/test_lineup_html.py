import unittest
from nivon.lineup_html import ContratoTabela, ErroLineup, analisar_html_lineup
from nivon.portos import contar_escalas


class TestLineupHtmlOffline(unittest.TestCase):
    def contrato(self):
        return ContratoTabela(
            "SANTOS",
            {"navio": "Navio", "duv": "DUV", "produto": "Produto", "toneladas": "Volume"},
            "https://exemplo.invalid/fixture-sintetica", "2026-10-16T12:00:00Z")

    def tabela(self, *linhas):
        linhas_html = "".join(f"<tr><td>{n}</td><td>{d}</td><td>{p}</td><td>{v}</td></tr>"
                             for n, d, p, v in linhas)
        return ("<table><thead><tr><th>Navio</th><th>DUV</th><th>Produto</th>"
                "<th>Volume</th></tr></thead><tbody>" + linhas_html + "</tbody></table>")

    def test_extrai_navios_sem_promover_status(self):
        html = self.tabela(("NAVIO A", "DUV-1", "SOJA", "1.234,50"),
                           ("NAVIO B", "DUV-2", "MILHO", "200"))
        x = analisar_html_lineup(html, self.contrato())
        self.assertEqual(x["quantidade_linhas"], 2)
        self.assertEqual(x["registros"][0].toneladas_programadas, 1234.5)
        self.assertEqual(x["registros"][0].status, "PROGRAMADO")

    def test_duas_linhas_um_duv_uma_escala(self):
        html = self.tabela(("NAVIO A", "DUV-1", "SOJA", "100"),
                           ("NAVIO A", "DUV-1", "MILHO", "200"))
        x = analisar_html_lineup(html, self.contrato())
        self.assertEqual(contar_escalas(x["registros"])["escalas_distintas_identificadas"], 1)

    def test_tabela_ausente_erro(self):
        with self.assertRaises(ErroLineup):
            analisar_html_lineup("<html>sem tabela</html>", self.contrato())

    def test_tabela_ambigua_erro(self):
        html = self.tabela(("NAVIO A", "1", "SOJA", "100"))
        with self.assertRaises(ErroLineup):
            analisar_html_lineup(html + html, self.contrato())

    def test_rowspan_nao_interpretado_errado(self):
        html = ('<table><tr><th>Navio</th><th>DUV</th><th>Produto</th><th>Volume</th></tr>'
                '<tr><td rowspan="2">NAVIO A</td><td>1</td><td>SOJA</td><td>100</td></tr></table>')
        with self.assertRaises(ErroLineup):
            analisar_html_lineup(html, self.contrato())

    def test_ausencia_duv_nao_gera_escala_identificada(self):
        x = analisar_html_lineup(self.tabela(("NAVIO A", "", "SOJA", "100")), self.contrato())
        self.assertEqual(contar_escalas(x["registros"])["escalas_distintas_identificadas"], 0)

    def test_sem_navio_rejeita(self):
        with self.assertRaises(ErroLineup):
            analisar_html_lineup(self.tabela(("", "2", "MILHO", "100")), self.contrato())

    def test_tonelada_com_formato_desconhecido_rejeita(self):
        with self.assertRaises(ErroLineup):
            analisar_html_lineup(self.tabela(("NAVIO A", "1", "SOJA", "1,200.50")), self.contrato())


if __name__ == "__main__":
    unittest.main()
