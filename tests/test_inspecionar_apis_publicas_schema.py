import unittest
from io import BytesIO
from unittest.mock import patch
from scripts.inspecionar_apis_publicas_schema import verificar_estrutura,URL_SIDRA,URL_PTAX

class _Resp:
    status=200
    def __init__(self,url,raw,mime="application/json"):
        self.url=url;self.buf=BytesIO(raw);self.headers={"Content-Type":mime}
    def __enter__(self):return self
    def __exit__(self,*args):return False
    def geturl(self):return self.url
    def read(self,n):return self.buf.read(n)
class _Opener:
    def __init__(self,source):self.source=source
    def open(self,req,timeout=15):return self.source(req.full_url)

class TestSchemaProbe(unittest.TestCase):
    def test_header_sidra_nao_imprime_linha_de_dados(self):
        raw=(b'[{"D1C":"Municipio (Codigo)","D2C":"Ano (Codigo)",'
             b'"D3C":"Variavel (Codigo)","D4C":"Produto (Codigo)",'
             b'"V":"Valor","MN":"Unidade de medida"},'
             b'{"D1C":"5107925","V":"SEGREDO_DADO"}]')
        x=verificar_estrutura("SIDRA",opener=_Opener(lambda u:_Resp(u,raw)))
        self.assertEqual(x["estado"],"HEADER_RECEBIDO_SEM_HOMOLOGACAO")
        self.assertNotIn("SEGREDO_DADO",str(x))
        self.assertNotIn("5107925",str(x))
    def test_ptax_sem_valores_individuais(self):
        raw=b'{"value":[{"cotacaoCompra":12345,"cotacaoVenda":12346,"dataHoraCotacao":"SECRET"}]}'
        x=verificar_estrutura("PTAX",opener=_Opener(lambda u:_Resp(u,raw)))
        self.assertNotIn("12345",str(x))
        self.assertNotIn("SECRET",str(x))
        self.assertIn("cotacaoCompra",x["campos_de_uma_cotacao"])
    def test_redirecionamento_bloqueado(self):
        opener=_Opener(lambda u:_Resp("https://other.example",b'{"value":[]}'))
        self.assertEqual(verificar_estrutura("PTAX",opener=opener)["estado"],
                         "STATUS_OU_REDIRECT_INESPERADO")
    def test_nao_interpreta_html_waf(self):
        x=verificar_estrutura("PTAX",opener=_Opener(
            lambda u:_Resp(u,b"<html>blocked</html>","text/html")))
        self.assertEqual(x["estado"],"MIME_NAO_JSON")
    def test_provedor_nao_previsto_nao_abre_rede(self):
        with self.assertRaises(ValueError):
            verificar_estrutura("PRIVATE")

    def test_sem_explicit_yes_nao_chama_rede(self):
        from scripts.inspecionar_apis_publicas_schema import main
        with patch("scripts.inspecionar_apis_publicas_schema.build_opener",
                   side_effect=AssertionError("rede indevida")):
            self.assertEqual(main([]),2)
