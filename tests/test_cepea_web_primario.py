"""CEPEA: extracao deterministica sem widgets nem fallback."""
import unittest
from datetime import date,datetime,timezone
from nivon.cepea_web_primario import extrair_precos_html,CepeaNaoHomologado,valor_real

HTML='''<html><body>
<h3>INDICADOR DA SOJA CEPEA/ESALQ - PARANAGUÁ</h3>
<table><tr><th>Data</th><th>Valor R$</th></tr>
<tr><td>21/10/2026</td><td>150,70</td></tr>
<tr><td>20/10/2026</td><td>151,25</td></tr></table>
<h3>INDICADOR DA SOJA CEPEA/ESALQ - PARANÁ</h3>
<table><tr><th>Data</th><th>Valor R$</th></tr>
<tr><td>21/10/2026</td><td>141,35</td></tr></table>
</body></html>'''
class TestCEPEA(unittest.TestCase):
    def extract(self,s=HTML):
        return extrair_precos_html(s,("soja_paranagua","soja_parana"),
            hoje=date(2026,10,22),
            coleta=datetime(2026,10,22,tzinfo=timezone.utc))
    def test_serie_e_praca_nao_misturadas(self):
        rows=self.extract()
        self.assertEqual(len(rows),3)
        self.assertEqual([x["valor"] for x in rows if x["serie_id"]=="soja_parana"],["141.35"])
        self.assertEqual([x["valor"] for x in rows if x["serie_id"]=="soja_paranagua"],["151.25","150.70"])
        self.assertTrue(all(x["licenca"]=="CC BY-NC 4.0" for x in rows))
        self.assertTrue(all(x["qualidade"]=="CANDIDATO_NAO_GRAVADO" for x in rows))
    def test_sem_tabela_falha_sem_fallback(self):
        with self.assertRaises(CepeaNaoHomologado):
            self.extract("<h2>Notícias Agrícolas</h2><table></table>")
    def test_rejeita_futura(self):
        s=HTML.replace("21/10/2026","23/10/2026")
        with self.assertRaises(CepeaNaoHomologado):
            self.extract(s)
    def test_rejeita_preco_zero_e_ambiguo(self):
        for x in ("0,00","NaN","1.500.50","", "-4,20"):
            with self.subTest(x=x),self.assertRaises(CepeaNaoHomologado):
                valor_real(x)
    def test_br_decimal(self):
        self.assertEqual(valor_real("1.245,77"),"1245.77")
    def test_tabelas_duplicadas_bloqueadas(self):
        s=HTML.replace("</body>", "<h3>INDICADOR DA SOJA CEPEA/ESALQ - PARANÁ</h3><table><tr><td>21/10/2026</td><td>142,00</td></tr></table></body>")
        with self.assertRaises(CepeaNaoHomologado):
            self.extract(s)
if __name__=="__main__":
    unittest.main()
