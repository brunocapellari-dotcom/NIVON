"""Contrato e API do terminal privado NIVON sem rede, IAM ou custo."""
import json
import threading
import unittest
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, timezone
from decimal import Decimal
from http.server import ThreadingHTTPServer
from urllib.request import urlopen
from urllib.error import HTTPError
from types import SimpleNamespace

from nivon.terminal_web import (
    ANOS_INICIAIS,LIMITE_BYTES,TerminalState,
    consultar_ferrovia,interpretar_serie,servidor,TTL_SEGUNDOS,
)
from nivon.transporte_multimodal import ErroTransporte


NOW=datetime(2026,10,25,20,30,tzinfo=timezone.utc)


def rows():
    return [{
        "ano":year,"registros":120,
        "tu":"10000",
        "ultima_competencia":f"{year}-"+("08" if year==2026 else "12"),
        "versoes_sha":1,
        "arquivo_sha256":"a"*64,
        "campos_ausentes":0,
        "ultima_referencia":date(year,8 if year==2026 else 12,1),
        "ultima_coleta":NOW,
    } for year in range(2006,2027)]


class FakeSDK:
    class ScalarQueryParameter:
        def __init__(self,name,typ,value):
            self.name,self.typ,self.value=name,typ,value
    class QueryJobConfig:
        def __init__(self,**kw):self.__dict__.update(kw)


class FakeBQ:
    def __init__(self,rs):
        self.rows=rs
        self.calls=[]
    def query(self,sql,job_config):
        self.calls.append((sql,job_config))
        return SimpleNamespace(result=lambda timeout:self.rows,total_bytes_processed=3123)


class TestSerie(unittest.TestCase):
    def test_proveniencia_e_tempos_distintos(self):
        doc=interpretar_serie(rows(),ultimo_ano=2026,agora=NOW)
        last=doc["serie"][-1]
        self.assertEqual(last["arquivo_sha256"],"a"*64)
        self.assertEqual(last["data_referencia"],"2026-08-01")
        self.assertEqual(last["data_coleta_utc"],NOW.isoformat())
        self.assertEqual(doc["freshness"]["idade_competencia_meses"],2)
        self.assertFalse(doc["freshness"]["sla_oficial"])

    def test_zero_observado_nao_e_nulo_ou_vazio(self):
        a=rows();a[-1]["tu"]="0"
        self.assertEqual(interpretar_serie(a,ultimo_ano=2026,agora=NOW)["serie"][-1]["toneladas_uteis"],"0")
        for value in (None,"", "NaN", "-1"):
            with self.subTest(value=value),self.assertRaises(ErroTransporte):
                a[-1]["tu"]=value
                interpretar_serie(a,ultimo_ano=2026,agora=NOW)
        with self.assertRaises(ErroTransporte):
            interpretar_serie([],ultimo_ano=2026,agora=NOW)

    def test_nulos_parciais_nao_sao_ocultados_pela_agregacao_sql(self):
        a=rows();a[-1]["campos_ausentes"]=1
        with self.assertRaises(ErroTransporte):
            interpretar_serie(a,ultimo_ano=2026,agora=NOW)

    def test_fonte_antiga_com_coleta_recente_continua_defasada(self):
        a=rows();a[-1].update(ultima_competencia="2026-03",ultima_referencia=date(2026,3,1))
        doc=interpretar_serie(a,ultimo_ano=2026,agora=NOW)
        self.assertEqual(doc["freshness"]["estado"],"SOURCE_LAG")
        self.assertEqual(doc["ultima_coleta_utc"],NOW.isoformat())
        self.assertEqual(doc["ultima_competencia"],"2026-03")

    def test_referencia_coleta_sha_e_fuso_invalidos_bloqueiam(self):
        changes=[("arquivo_sha256",None),("arquivo_sha256","z"*64),
                 ("ultima_referencia",date(2026,7,1)),
                 ("ultima_coleta",datetime(2026,7,1,tzinfo=timezone.utc)),
                 ("ultima_coleta",NOW.replace(tzinfo=None))]
        for key,value in changes:
            with self.subTest(key=key,value=value),self.assertRaises(ErroTransporte):
                a=rows();a[-1][key]=value
                interpretar_serie(a,ultimo_ano=2026,agora=NOW)

    def test_leitura_idempotente_sem_dml_e_com_limite_em_todas_as_queries(self):
        client=FakeBQ(rows())
        before=rows()
        first=consultar_ferrovia(cliente=client,sdk=FakeSDK,agora=NOW)
        self.assertEqual(first,consultar_ferrovia(cliente=client,sdk=FakeSDK,agora=NOW))
        self.assertEqual(client.rows,before)
        self.assertEqual(len(client.calls),2)
        for sql,cfg in client.calls:
            self.assertEqual(cfg.maximum_bytes_billed,250_000_000)
            self.assertTrue(sql.startswith("SELECT "))
            self.assertIn("COUNTIF(",sql)
            self.assertNotRegex(sql,r"\b(INSERT|UPDATE|DELETE|MERGE|CREATE)\b")

    def test_expiracao_concorrente_e_falha_nao_retornam_cache_vencido(self):
        now=[0.];calls=[];fail=[False]
        def source():
            calls.append(1)
            if fail[0]:raise RuntimeError("INTERNAL_SECRET")
            return {"estado":"ANTT_SERIE_OBSERVADA_DECLARADA","generation":len(calls)}
        state=TerminalState(consulta=source,relogio=lambda:now[0])
        with ThreadPoolExecutor(max_workers=8) as pool:
            self.assertEqual([x["generation"] for x in pool.map(lambda _:state.obter(),range(16))],[1]*16)
        now[0]=TTL_SEGUNDOS
        self.assertEqual(state.obter()["generation"],2)
        fail[0]=True;now[0]+=TTL_SEGUNDOS
        with self.assertRaises(RuntimeError):state.obter()
        fail[0]=False
        self.assertEqual(state.obter()["generation"],4)

    def test_agregados_reais_e_ano_parcial(self):
        doc=interpretar_serie(rows(),ultimo_ano=2026,agora=NOW)
        self.assertEqual(doc["anos"],21)
        self.assertEqual(doc["registros_acumulados"],2520)
        self.assertEqual(doc["tu_acumuladas"],"210000")
        self.assertEqual(doc["ultima_competencia"],"2026-08")
        self.assertTrue(doc["serie"][-1]["parcial"])
        self.assertFalse(doc["serie"][-2]["parcial"])
        self.assertFalse(doc["homologacao_editorial"])
        self.assertFalse(doc["soma_multimodal_permitida"])
        self.assertFalse(doc["point_in_time_historico"])

    def test_anos_faltantes_nao_viram_zero(self):
        with self.assertRaisesRegex(ErroTransporte,"incompleto"):
            interpretar_serie(rows()[:-1],ultimo_ano=2026,agora=NOW)

    def test_revisoes_duplas_bloqueiam(self):
        a=rows();a[0]["versoes_sha"]=2
        with self.assertRaises(ErroTransporte):
            interpretar_serie(a,ultimo_ano=2026,agora=NOW)

    def test_futuro_bloqueia(self):
        a=rows();a[-1]["ultima_competencia"]="2026-12"
        with self.assertRaisesRegex(ErroTransporte,"futura"):
            interpretar_serie(a,ultimo_ano=2026,agora=NOW)

    def test_fonte_real_bq_query_limitada(self):
        client=FakeBQ(rows())
        doc=consultar_ferrovia(cliente=client,sdk=FakeSDK,agora=NOW)
        self.assertEqual(doc["estado"],"ANTT_SERIE_OBSERVADA_DECLARADA")
        sql,cfg=client.calls[0]
        self.assertTrue(sql.startswith("SELECT ano,"))
        self.assertIn("vw_antt_ferrovia_od_atual",sql)
        self.assertIn("AND @fim",sql)
        self.assertEqual(cfg.maximum_bytes_billed,LIMITE_BYTES)
        self.assertTrue(cfg.use_query_cache)
        self.assertEqual(cfg.query_parameters[0].value,2026)
        self.assertEqual(doc["bytes_processados_ultimo_job"],3123)

    def test_mantem_cache_para_nao_disparar_query_em_cada_usuario(self):
        now=[0.]
        chamadas=[]
        def source():
            chamadas.append(1)
            return {"estado":"ANTT_SERIE_OBSERVADA_DECLARADA"}
        state=TerminalState(consulta=source,relogio=lambda:now[0])
        state.obter();state.obter()
        self.assertEqual(len(chamadas),1)
        now[0]=TTL_SEGUNDOS+0.1
        state.obter()
        self.assertEqual(len(chamadas),2)


class TestAPI(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.doc=interpretar_serie(rows(),ultimo_ano=2026,agora=NOW)
        cls.app=ThreadingHTTPServer(("127.0.0.1",0),
                                   servidor(TerminalState(consulta=lambda:cls.doc)))
        cls.thread=threading.Thread(target=cls.app.serve_forever,daemon=True)
        cls.thread.start()
        cls.url="http://127.0.0.1:"+str(cls.app.server_port)

    @classmethod
    def tearDownClass(cls):
        cls.app.shutdown()
        cls.app.server_close()
        cls.thread.join(timeout=3)

    def test_healthnao_consulta_cloud(self):
        with urlopen(self.url+"/healthz",timeout=3) as r:
            self.assertEqual(r.status,200)
            self.assertEqual(json.load(r)["estado"],"PROCESSO_ATIVO")

    def test_readiness_separada_do_health(self):
        with urlopen(self.url+'/readyz',timeout=3) as r:
            self.assertEqual(json.load(r)['estado'],'PRONTO_PARA_LEITURA')

    def test_readiness_fonte_defasada_503_api_preserva_competencia(self):
        data=rows();data[-1].update(ultima_competencia='2026-03',ultima_referencia=date(2026,3,1))
        doc=interpretar_serie(data,ultimo_ano=2026,agora=NOW)
        app=ThreadingHTTPServer(('127.0.0.1',0),servidor(TerminalState(consulta=lambda:doc)))
        task=threading.Thread(target=app.serve_forever,daemon=True);task.start()
        base=f'http://127.0.0.1:{app.server_port}'
        try:
            with urlopen(base+'/healthz',timeout=3) as r:self.assertEqual(r.status,200)
            with self.assertRaises(HTTPError) as err:urlopen(base+'/readyz',timeout=3)
            self.assertEqual(err.exception.code,503)
            self.assertEqual(json.load(err.exception)['estado'],'SOURCE_LAG')
            with urlopen(base+'/api/v1/ferrovia',timeout=3) as r:
                self.assertEqual(json.load(r)['ultima_competencia'],'2026-03')
        finally:app.shutdown();app.server_close();task.join(timeout=3)

    def test_portal_unico_assets_csp_e_modulos_sem_dados(self):
        with urlopen(self.url+"/",timeout=3) as r:
            html=r.read().decode()
            self.assertIn('/assets/portal.js',html)
            self.assertIn('/assets/portal.css',html)
            self.assertIn('FONTE NÃO DISPONÍVEL NESTE TERMINAL',html)
            self.assertNotIn('<script>',html)
            self.assertNotIn("unsafe-inline",r.headers["Content-Security-Policy"])
        for name,mime in (("portal.js","text/javascript"),("portal.css","text/css")):
            with urlopen(self.url+"/assets/"+name,timeout=3) as r:
                self.assertTrue(r.headers["Content-Type"].startswith(mime))
                self.assertGreater(len(r.read()),100)
                self.assertEqual(r.headers["Cache-Control"],"no-store")
        for route in ('/assets/../terminal_web.py','/assets/%2e%2e/terminal_web.py','/.env','/api/v1/painel'):
            with self.assertRaises(HTTPError) as err:
                urlopen(self.url+route,timeout=3)
            self.assertEqual(err.exception.code,404)

    def test_html_nao_exibe_dados_sinteticos_antes_da_api(self):
        with urlopen(self.url+"/",timeout=3) as r:
            html=r.read().decode()
            self.assertIn("NIVON",html)
            self.assertIn("Carregando dados reais",html)
            self.assertIn("noindex",html)
            self.assertNotIn("9,953 bilhões",html)
            self.assertEqual(r.headers["X-Frame-Options"],"DENY")

    def test_api_json_com_natureza_e_proibicoes(self):
        with urlopen(self.url+"/api/v1/ferrovia",timeout=3) as r:
            doc=json.load(r)
            self.assertEqual(doc["anos"],21)
            self.assertEqual(doc["natureza"],"OBSERVADO_DECLARADO")
            self.assertFalse(doc["homologacao_editorial"])
            self.assertIn("ANTT/SIADE",doc["fonte"])
            self.assertEqual(doc["ultima_competencia"],"2026-08")
            self.assertEqual(doc["serie"][-1]["arquivo_sha256"],"a"*64)
            self.assertEqual(r.headers["Cache-Control"],"no-store")

    def test_erro_interno_nao_vaza_segredos(self):
        bad=ThreadingHTTPServer(("127.0.0.1",0),
           servidor(TerminalState(consulta=lambda:(_ for _ in ()).throw(
               RuntimeError("GCP-CREDENTIAL-SENSITIVE")))))
        task=threading.Thread(target=bad.serve_forever,daemon=True)
        task.start()
        try:
            with self.assertRaises(HTTPError) as context:
                urlopen(f"http://127.0.0.1:{bad.server_port}/api/v1/ferrovia",timeout=3)
            self.assertEqual(context.exception.code,503)
            body=context.exception.read().decode()
            self.assertNotIn("SENSITIVE",body)
        finally:
            bad.shutdown();bad.server_close();task.join(timeout=3)

    def test_nao_aceita_post(self):
        from urllib.request import Request
        with self.assertRaises(HTTPError) as e:
            urlopen(Request(self.url+"/api/v1/ferrovia",data=b"{}",method="POST"),timeout=3)
        self.assertEqual(e.exception.code,405)


if __name__=="__main__":
    unittest.main()
