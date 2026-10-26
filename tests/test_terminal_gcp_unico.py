"""Backend unico GCP: mercado, portal e ferrovia sao rotas do mesmo HTTP."""
import json
import threading
import unittest
from datetime import datetime, timezone
from http.server import ThreadingHTTPServer
from urllib.error import HTTPError
from urllib.request import urlopen
from pathlib import Path

from nivon.mercado_bcb_ro import consultar, parse, ErroBCB
from nivon.terminal_web import servidor, TerminalState

NOW=datetime(2026,10,25,18,0,tzinfo=timezone.utc)

class ConsolidacaoGCP(unittest.TestCase):
    def test_bcb_preserva_data_unidade_e_status(self):
        reader=lambda code:[{"data":"23/10/2026",
                              "valor":"5,0523" if code==1 else "0,050788"}]
        doc=consultar(now=NOW,reader=reader)
        self.assertEqual(doc["status"],"DISPONIVEL")
        self.assertFalse(doc["nuvem_google_atualizada"])
        self.assertEqual(doc["series"]["ptax_usd_venda"]["unit"],"BRL/USD")
        self.assertEqual(doc["series"]["selic_diaria"]["value"],0.050788)

    def test_bcb_nao_fabrica_valor_quando_fonte_falha(self):
        def source(code):
            if code==11: raise TimeoutError("sem resposta")
            return [{"data":"01/10/2026","valor":"5.012"}]
        doc=consultar(now=NOW,reader=source)
        self.assertEqual(doc["status"],"PARCIAL")
        self.assertEqual(doc["series"]["ptax_usd_venda"]["status"],"SOURCE_LAG")
        self.assertIsNone(doc["series"]["selic_diaria"]["value"])

    def test_dados_invalidos_bloqueados(self):
        for date,value in [("31/02/2026","5"),("26/10/2026","5"),
                           ("23/10/2026","NaN"),("23/10/2026","-1")]:
            with self.assertRaises(ErroBCB):
                parse([{"data":date,"valor":value}],NOW)

    def test_web_servido_pelo_cloudrun_sem_serverless_extra(self):
        calls=[]
        def market():
            calls.append(1)
            return consultar(now=NOW,reader=lambda code:[{
                "data":"23/10/2026","valor":"5"}])
        state=TerminalState(consulta=lambda:{"estado":"ANTT_SERIE_OBSERVADA_DECLARADA"},
                            mercado=market)
        srv=ThreadingHTTPServer(("127.0.0.1",0),servidor(state))
        worker=threading.Thread(target=srv.serve_forever,daemon=True)
        worker.start()
        base="http://127.0.0.1:"+str(srv.server_port)
        try:
            with urlopen(base+"/painel",timeout=3) as r:
                html=r.read()
                self.assertIn(b"NIVON",html)
                self.assertEqual(r.headers["X-Frame-Options"],"DENY")
            for route in ("/assets/nivon.css","/assets/nivon.js","/assets/mercado.js"):
                with urlopen(base+route,timeout=3) as r:
                    self.assertGreater(len(r.read()),100)
            with urlopen(base+"/api/mercado",timeout=3) as r:
                self.assertEqual(json.load(r)["status"],"DISPONIVEL")
            with urlopen(base+"/api/mercado",timeout=3) as r:
                self.assertEqual(json.load(r)["status"],"DISPONIVEL")
            self.assertEqual(len(calls),1)  # cache 10 minutos
            with self.assertRaises(HTTPError) as ex:
                urlopen(base+"/assets/.env",timeout=3)
            self.assertEqual(ex.exception.code,404)
        finally:
            srv.shutdown()
            srv.server_close()
            worker.join(timeout=3)

    def test_imagem_empacota_assets_sem_outro_provedor(self):
        root=Path(__file__).resolve().parents[1]
        docker=(root/"infra/google_cloud/Dockerfile.terminal").read_text()
        self.assertIn("COPY public ./public",docker)
        self.assertIn("nivon.terminal_web",docker)
        self.assertNotIn("vercel",docker.lower())

if __name__=="__main__":
    unittest.main()
