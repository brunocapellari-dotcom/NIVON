"""CEPEA: impedir que urllib siga 30x até host não verificado."""
import unittest
from unittest.mock import patch
from urllib.error import HTTPError
from urllib.request import Request

from nivon.cepea_web_primario import (
    URL_SOJA, _BloquearRedirecionamentos, consultar_pagina_primaria,
    CepeaNaoHomologado,
)


class Resposta:
    def __init__(self,url): self.url=url
    def geturl(self): return self.url
    def read(self,size): return b"<html>ok</html>"
    @property
    def headers(self):
        class Headers:
            def get_content_charset(self):return "utf-8"
        return Headers()
    def __enter__(self): return self
    def __exit__(self,*args):return False


class HTTPCEPEASeguro(unittest.TestCase):
    def test_redirecionador_recusa_antes_de_contatar_destino(self):
        handler=_BloquearRedirecionamentos()
        self.assertIsNone(handler.redirect_request(
            Request(URL_SOJA),None,302,"Moved",
            {"Location":"http://127.0.0.1/"}, "http://127.0.0.1/"))

    def test_abertura_default_instala_handler_sem_redirecionamento(self):
        class Opener:
            def open(self,request,timeout):
                self.called=(request.full_url,timeout)
                return Resposta(URL_SOJA)
        opener=Opener()
        with patch("nivon.cepea_web_primario.build_opener",
                   return_value=opener) as factory:
            html=consultar_pagina_primaria(URL_SOJA)
        self.assertEqual(html,"<html>ok</html>")
        factory.assert_called_once()
        self.assertIsInstance(factory.call_args.args[0],_BloquearRedirecionamentos)
        self.assertEqual(opener.called,(URL_SOJA,18))

    def test_redirecionamento_de_url_forjada_recusado(self):
        with self.assertRaises(CepeaNaoHomologado):
            consultar_pagina_primaria(
                URL_SOJA,open_url=lambda req,timeout:
                Resposta("https://127.0.0.1/admin"))

if __name__=="__main__":
    unittest.main()
