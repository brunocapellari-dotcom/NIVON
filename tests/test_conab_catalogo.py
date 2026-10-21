import unittest
from nivon.conab_catalogo import descobrir_planilhas, ErroCatalogoConab


class TestCatalogoCONAB(unittest.TestCase):
    def soja(self):
        return ('<html><a href="/conab/serie/@@download/soja.xls">'
                'SojaSerieHist.xls</a></html>')

    def milho(self):
        nomes = ("Milho1aSerieHist.xls", "Milho2aSerieHist.xls",
                 "Milho3aSerieHist.xls", "MilhoTotalSerieHist.xls")
        return "<html>" + "".join(
            f'<a href="/conab/serie/{x}">{x}</a>' for x in nomes
        ) + "</html>"

    def test_soja_link_oficial(self):
        x = descobrir_planilhas(self.soja(), "SOJA")
        self.assertEqual(len(x), 1)
        self.assertTrue(x[0]["url"].startswith("https://www.gov.br/"))
        self.assertFalse(x[0]["coleta_habilitada"])

    def test_milho_quatro_series_distintas(self):
        x = descobrir_planilhas(self.milho(), "MILHO")
        self.assertEqual(len(x), 4)
        self.assertEqual(len({z["arquivo"] for z in x}), 4)

    def test_planilha_ausente_rejeita(self):
        with self.assertRaises(ErroCatalogoConab):
            descobrir_planilhas("<html>sem planilha</html>", "SOJA")

    def test_redirecionamento_para_host_nao_oficial_rejeita(self):
        html = '<a href="https://exemplo.invalid/x.xls">SojaSerieHist.xls</a>'
        with self.assertRaises(ErroCatalogoConab):
            descobrir_planilhas(html, "SOJA")

    def test_link_ambiguo_rejeita(self):
        html = self.soja().replace("</html>", (
            '<a href="/outro.xls">SojaSerieHist.xls</a></html>'))
        with self.assertRaises(ErroCatalogoConab):
            descobrir_planilhas(html, "SOJA")

    def test_nao_confunde_documentos_ou_produtos(self):
        with self.assertRaises(ErroCatalogoConab):
            descobrir_planilhas(self.soja(), "MILHO")
        with self.assertRaises(ErroCatalogoConab):
            descobrir_planilhas(self.soja(), "SORGO")


if __name__ == "__main__":
    unittest.main()
