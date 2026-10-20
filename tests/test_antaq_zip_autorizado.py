import io
import unittest
from zipfile import ZipFile

from nivon.antaq_zip_autorizado import (
    DireitosAntaq, endpoint_antaq, adquirir_arquivo_antaq
)
from nivon.antaq_historico_offline import ErroAntaq


class _Resposta:
    def __init__(self,url,corpo,mime="application/zip",status=200):
        self.url=url
        self.corpo=io.BytesIO(corpo)
        self.headers={"Content-Type":mime}
        self.status=status
    def geturl(self):
        return self.url
    def read(self,size=-1):
        return self.corpo.read(size)
    def __enter__(self):
        return self
    def __exit__(self,*args):
        self.corpo.close()


class _Cliente:
    def __init__(self,corpo,mime="application/zip",wrong_url=None,status=200):
        self.corpo=corpo
        self.mime=mime
        self.wrong_url=wrong_url
        self.status=status
        self.calls=0
    def open(self,req,timeout):
        self.calls+=1
        return _Resposta(self.wrong_url or req.full_url,self.corpo,self.mime,self.status)


class TestAntaqZipAutorizado(unittest.TestCase):
    def licenca(self):
        return DireitosAntaq(status="APROVADA",
                            operacoes=frozenset({"LEITURA","COLETA","ARMAZENAMENTO"}),
                            evidencia_id="AUTORIZACAO_SINTETICA_TESTE")

    def zip_mock(self):
        b=io.BytesIO()
        with ZipFile(b,"w") as z:
            z.writestr("2024Carga.txt","IDCarga;IDAtracacao\n1;2\n")
        return b.getvalue()

    def test_endpoint_exatamente_ano_ou_catalogo(self):
        self.assertEqual(endpoint_antaq(tipo="ANUAL",ano=2024,
                          em="2026-10-19T22:00:00-03:00"),
                         "https://estatistica.antaq.gov.br/ea/txt/2024.zip")
        self.assertTrue(endpoint_antaq(tipo="MERCADORIAS",
                         em="2026-10-19T22:00:00-03:00").endswith("Mercadoria.zip"))

    def test_without_rights_never_requests(self):
        client=_Cliente(self.zip_mock())
        with self.assertRaises(PermissionError):
            adquirir_arquivo_antaq(tipo="ANUAL",ano=2024,em="2026-10-19T22:00:00-03:00",
                                   direitos=DireitosAntaq(),abridor=client)
        self.assertEqual(client.calls,0)

    def test_mock_response_validated_not_published(self):
        client=_Cliente(self.zip_mock())
        r=adquirir_arquivo_antaq(tipo="ANUAL",ano=2024,em="2026-10-19T22:00:00-03:00",
                                direitos=self.licenca(),abridor=client)
        self.assertEqual(client.calls,1)
        self.assertIn("NAO_HOMOLOGA",r["classificacao"])
        self.assertEqual(r["bytes"],len(self.zip_mock()))

    def test_waf_html_http_200_bloqueado(self):
        client=_Cliente(b"<html>Cloudflare challenge</html>",mime="text/html")
        with self.assertRaises(ErroAntaq):
            adquirir_arquivo_antaq(tipo="ANUAL",ano=2024,em="2026-10-19T22:00:00-03:00",
                                    direitos=self.licenca(),abridor=client)

    def test_https_redirect_not_allowed(self):
        client=_Cliente(self.zip_mock(),wrong_url="https://www.gov.br/antaq/indisponivel")
        with self.assertRaises(ErroAntaq):
            adquirir_arquivo_antaq(tipo="ANUAL",ano=2024,em="2026-10-19T22:00:00-03:00",
                                    direitos=self.licenca(),abridor=client)

    def test_future_year_prohibited(self):
        with self.assertRaises(ErroAntaq):
            endpoint_antaq(tipo="ANUAL",ano=2030,em="2026-10-19T22:00:00-03:00")

if __name__=="__main__":
    unittest.main()
