"""Smoke integrado do painel HTTP local, sem GCP, terceiros ou rede externa."""
from __future__ import annotations

import http.client
import json
import threading
import unittest
from unittest.mock import Mock

from nivon.painel_local_mvp import APP_STATUS, construir_servidor
from nivon.piloto_ptax_readonly import ErroPiloto


def value():
    return {
        "schema":"NIVON_PTAX_USD_READONLY_MVP_V1",
        "status":"PREVIA_INTERNA_VALIDA",
        "cotacao_venda":5.35,
        "cotacao_compra":5.33,
        "variacao_venda_pct_vs_dia_anterior_observado":.6,
        "referencia_utc":"2026-10-23T16:10:00+00:00",
        "competencia":"2026-10-23",
        "coletado_utc":"2026-10-25T18:00:00+00:00",
        "idade_horas":49.8,
        "aprovado_go_live":False,
        "publicacao_autorizada":False,
    }


class PainelMVPHTTP(unittest.TestCase):
    def setUp(self):
        self.consulta=Mock(return_value=value())
        self.server=construir_servidor(porta=0, consulta=self.consulta)
        self.thread=threading.Thread(target=self.server.serve_forever,daemon=True)
        self.thread.start()
        self.addCleanup(self.close)

    def close(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=3)

    def get(self,uri):
        c=http.client.HTTPConnection("127.0.0.1",self.server.server_port,timeout=5)
        c.request("GET",uri)
        res=c.getresponse()
        result=res.status,dict(res.getheaders()),res.read()
        c.close()
        return result

    def test_page_and_health_are_safe_without_network(self):
        status,headers,body=self.get("/")
        self.assertEqual(status,200)
        self.assertIn(b"NIVON",body)
        self.assertIn(b"CONAB",body)
        self.assertIn(b"CEPEA",body)
        self.assertIn(b"Indispon",body)
        self.assertEqual(headers["Cache-Control"],"no-store")
        self.assertIn("default-src 'none'",headers["Content-Security-Policy"])
        status,_,body=self.get("/healthz")
        self.assertEqual(status,200)
        payload=json.loads(body)
        self.assertEqual(payload["estado"],APP_STATUS)
        self.assertIs(payload["dados_atuais_confirmados"],False)
        self.consulta.assert_not_called()

    def test_api_returns_prices_only_after_explicit_browser_request(self):
        self.assertEqual(self.consulta.call_count,0)
        status,headers,body=self.get("/api/ptax")
        self.assertEqual(status,200)
        data=json.loads(body)
        self.assertEqual(data["cotacao_venda"],5.35)
        self.assertIs(data["aprovado_go_live"],False)
        self.assertEqual(headers["Cache-Control"],"no-store")
        self.assertEqual(self.consulta.call_count,1)
        status,_,body=self.get("/api/ptax")
        self.assertEqual(status,200)
        self.assertEqual(self.consulta.call_count,1)  # cache volátil

    def test_source_error_returns_503_and_never_uses_old_quote(self):
        self.consulta.side_effect=ErroPiloto("dados inválidos")
        status,_,body=self.get("/api/ptax")
        self.assertEqual(status,503)
        data=json.loads(body)
        self.assertEqual(data["status"],"INDISPONIVEL")
        self.assertNotIn("cotacao_venda",data)

    def test_invalid_queries_or_unknown_paths_do_not_call_source(self):
        for url,expected in [("/api/ptax?override=evil",400),
                             ("/api/notfound",404),("/hidden",404)]:
            with self.subTest(url=url):
                s,_,body=self.get(url)
                self.assertEqual(s,expected)
        self.consulta.assert_not_called()

    def test_cannot_bind_to_public_interfaces(self):
        for host in ("0.0.0.0","localhost","::","192.168.0.1"):
            with self.subTest(host=host),self.assertRaisesRegex(ValueError,"localhost"):
                construir_servidor(host=host,porta=0,consulta=self.consulta)


if __name__=="__main__":
    unittest.main()
