"""Go-live contratual NIVON: cliente falso, sem rede e sem custo GCP."""
import json
from datetime import datetime, timezone
from http.server import ThreadingHTTPServer
from threading import Thread
from types import SimpleNamespace
import unittest
import urllib.error
import urllib.request

from nivon.terminal_web import (
    Cache, FalhaTerminal, Handler, RAIL_SQL, ROAD_SQL,
    MAX_BYTES_PER_QUERY, extrair_snapshot, consultar_snapshot,
)

def ferrovia():
    return [
        SimpleNamespace(polo_id="MT_RONDONOPOLIS_FERRO",tu="24258027"),
        SimpleNamespace(polo_id="MT_ITIQUIRA_FERRO",tu="742649"),
        SimpleNamespace(polo_id="MT_ALTO_ARAGUAIA_FERRO",tu="1458596"),
    ]

def rodovia():
    return [SimpleNamespace(n=16,tu="98170287",revisions=1)]

class SDK:
    class QueryJobConfig:
        def __init__(self,**kwargs):self.__dict__.update(kwargs)

class BQ:
    def __init__(self,erro=False):
        self.calls=[]
        self.erro=erro
    def query(self,sql,job_config,location):
        self.calls.append((sql,job_config,location))
        if self.erro:raise RuntimeError("PERMISSION_DENIED secret-name")
        rows=ferrovia() if "vw_nivon_corredores_ferrovia_mensal" in sql else rodovia()
        return SimpleNamespace(result=lambda timeout:rows)

class TerminalTests(unittest.TestCase):
    def test_snapshot_real_2025_sem_soma_ou_transbordo(self):
        obj=extrair_snapshot(ferrovia(),rodovia(),
                            agora=datetime(2026,10,25,tzinfo=timezone.utc))
        self.assertEqual(obj["estado"],"DADOS_REAIS_2025_CONFIRMADOS")
        self.assertEqual(obj["rodovia"]["linhas"],16)
        self.assertEqual(obj["rodovia"]["toneladas_top16"],"98170287")
        self.assertFalse(obj["rodovia"]["produto_identificado"])
        self.assertFalse(obj["soma_multimodal_permitida"])
        self.assertFalse(obj["transbordos_confirmados"])
        self.assertEqual(obj["recorte"],"HISTORICO_ANUAL_NAO_TEMPO_REAL")

    def test_falha_fechada_para_revisao_nova_e_falta_de_polo(self):
        for rail,road in (
            (ferrovia()[:2],rodovia()),
            (ferrovia()+ferrovia()[:1],rodovia()),
            (ferrovia(),[SimpleNamespace(n=15,tu="98170287",revisions=1)]),
            (ferrovia(),[SimpleNamespace(n=16,tu="98170287",revisions=2)]),
            (ferrovia(),[SimpleNamespace(n=16,tu="98170288",revisions=1)]),
        ):
            with self.subTest(rail=len(rail),road=road[0].n):
                with self.assertRaises(FalhaTerminal):
                    extrair_snapshot(rail,road)

    def test_sql_apenas_select_tabelas_fixas_e_teto(self):
        bq=BQ()
        d=consultar_snapshot(cliente=bq,sdk=SDK)
        self.assertEqual(d["rodovia"]["toneladas_top16"],"98170287")
        self.assertEqual(len(bq.calls),2)
        for sql,config,region in bq.calls:
            self.assertTrue(sql.startswith("SELECT "))
            self.assertNotIn("\\",sql)
            self.assertEqual(region,"southamerica-east1")
            self.assertEqual(config.maximum_bytes_billed,MAX_BYTES_PER_QUERY)
            self.assertTrue(config.use_query_cache)
        self.assertEqual(bq.calls[0][0],RAIL_SQL)
        self.assertEqual(bq.calls[1][0],ROAD_SQL)

    def test_cache_evitar_queries_repetidas_e_expirar(self):
        tick=[100]
        calls=[]
        def loader():
            calls.append(1)
            return {"rodovia":"ok"}
        c=Cache(loader=loader,clock=lambda:tick[0],ttl=600)
        self.assertEqual(c.get(),{"rodovia":"ok"})
        tick[0]=699
        self.assertEqual(c.get(),{"rodovia":"ok"})
        self.assertEqual(len(calls),1)
        tick[0]=701
        self.assertEqual(c.get(),{"rodovia":"ok"})
        self.assertEqual(len(calls),2)

    def test_servico_http_seguro_nega_falha_bq_sem_vazar_erro(self):
        Handler.cache=Cache(loader=lambda: (_ for _ in ()).throw(
            RuntimeError("secret-dataset-credentials")),ttl=600)
        server=ThreadingHTTPServer(("127.0.0.1",0),Handler)
        thread=Thread(target=server.serve_forever,daemon=True)
        thread.start()
        base=f"http://127.0.0.1:{server.server_address[1]}"
        try:
            with urllib.request.urlopen(base+"/healthz",timeout=3) as resp:
                data=json.load(resp)
                self.assertEqual(resp.status,200)
                self.assertFalse(data["data_verified"])
                self.assertEqual(resp.headers["X-Frame-Options"],"DENY")
                self.assertIn("default-src 'none'",resp.headers["Content-Security-Policy"])
            with urllib.request.urlopen(base+"/",timeout=3) as resp:
                html=resp.read().decode()
                self.assertIn("NIVON",html)
                self.assertIn("ACESSO INTERNO",html)
                self.assertNotIn("Dados ao vivo",html)
            with self.assertRaises(urllib.error.HTTPError) as error:
                urllib.request.urlopen(base+"/api/resumo",timeout=3)
            self.assertEqual(error.exception.code,503)
            payload=error.exception.read()
            self.assertNotIn(b"secret",payload)
            with self.assertRaises(urllib.error.HTTPError) as error:
                urllib.request.urlopen(base+"/api/operacoes/escrever",timeout=3)
            self.assertEqual(error.exception.code,404)
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=3)

    def test_endpoint_com_snapshot_carregado(self):
        Handler.cache=Cache(loader=lambda:extrair_snapshot(ferrovia(),rodovia()))
        server=ThreadingHTTPServer(("127.0.0.1",0),Handler)
        t=Thread(target=server.serve_forever,daemon=True)
        t.start()
        try:
            with urllib.request.urlopen(f"http://127.0.0.1:{server.server_address[1]}/api/resumo") as res:
                doc=json.load(res)
            self.assertEqual(doc["estado"],"DADOS_REAIS_2025_CONFIRMADOS")
            self.assertEqual(doc["ferrovia"]["polos"]["MT_ITIQUIRA_FERRO"],"742649")
        finally:
            server.shutdown();server.server_close();t.join(timeout=3)

if __name__=="__main__":
    unittest.main()
