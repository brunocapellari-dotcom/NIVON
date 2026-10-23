import unittest
from io import BytesIO
from scripts.inspecionar_mdic_indice import obter,INDEX
class R:
    status=200
    def __init__(self,raw,mime="text/html",url=INDEX):
        self.buf=BytesIO(raw);self.headers={"Content-Type":mime};self.url=url
    def __enter__(self):return self
    def __exit__(self,*args):return False
    def geturl(self):return self.url
    def read(self,n):return self.buf.read(n)
class Fake:
    def __init__(self,raw,mime="text/html"):self.raw=raw;self.mime=mime
    def open(self,req,timeout):
        return R(self.raw,self.mime)
class TestIndicesMDIC(unittest.TestCase):
    def test_nomes_metadados_nao_trazem_conteudo(self):
        html=b'<a href="https://dados.exemplo.gov.br/EXP_2026.csv">2026</a>'
        r=obter(abridor=Fake(html))
        self.assertEqual(r["status"],"METADADOS_LINKS_HTML_SEM_DOWNLOAD")
        self.assertEqual(r["arquivos_com_ano"]["2026"],1)
        self.assertEqual(r["coletados_csv"],0)
    def test_html_nunca_csv(self):
        self.assertEqual(obter(abridor=Fake(b"data",mime="text/csv"))["status"],"MIME_NAO_HTML")
