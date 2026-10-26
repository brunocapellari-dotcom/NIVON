"""MVP NIVON: HTTP, auth, gate de custo, proveniência e consumo máximo de 2 fontes."""
import hashlib
import io
import json
import os
import unittest
from datetime import datetime, timezone
from unittest.mock import patch

from nivon import terminal_mvp as mvp

TOKEN="nivel_interno_long_token_test_2026"
SHA=hashlib.sha256(TOKEN.encode()).hexdigest()
ENV={"NIVON_MVP_TOKEN_SHA256":SHA,"NIVON_MVP_BQ_READ_APPROVED":"true",
     "NIVON_BQ_PROJECT":"nivon-data","NIVON_BQ_DATASET":"nivon_raw"}
NOW=datetime(2026,10,25,21,0,tzinfo=timezone.utc)


def request(path, *,token=None,method="GET",query=""):
    state={}
    def responder(status,headers):
        state.update(status=status,headers=dict(headers))
    headers={} if token is None else {"HTTP_AUTHORIZATION":"Bearer "+token}
    with patch.dict(os.environ, ENV,clear=True):
        body=b"".join(mvp.app({"PATH_INFO":path,"REQUEST_METHOD":method,
                             "QUERY_STRING":query,**headers},responder))
    state["body"]=body
    return state


class FakeCalls:
    def __init__(self, fail=None):
        self.calls=[];self.fail=fail
    def rail(self,**kw):
        self.calls.append(("rail",kw))
        if self.fail=="rail":raise ValueError("internal secret path /hidden/file")
        return {"executado":True,"publicavel":False,"estado":"REVISAO_ATUAL",
            "polos_ferroviarios":[{"polo":{"id":"MT_RONDONOPOLIS_FERRO"},
                "toneladas_ferroviarias":"500"}],"linhas_view":2,
            "arquivos_sha256":["a"*64]}
    def sea(self,**kw):
        self.calls.append(("sea",kw))
        if self.fail=="sea":raise ValueError("credential-private")
        return {"executado":True,"publicavel":False,"estado":"PORTWATCH_TRANSITOS_ESTIMADOS_SHADOW",
            "dias_distintos":1,"revisoes_visiveis":2,
            "transitos_ais_reportados":11,"volume_estimado_modelo_t":"900",
            "nota":"Estimado, não realizado"}


class MVPTest(unittest.TestCase):
    def test_health_sem_bigquery_e_sem_homologacao(self):
        x=request("/healthz")
        self.assertEqual(x["status"],"200 OK")
        data=json.loads(x["body"])
        self.assertFalse(data["consultou_bigquery"])
        self.assertFalse(data["go_live_homologado"])

    def test_nao_expor_api_sem_token(self):
        for token in (None,"teste","outro_token_longo_que_foi_inventado"):
            x=request("/api/v1/resumo",token=token)
            self.assertEqual(x["status"],"401 Unauthorized")
            self.assertEqual(json.loads(x["body"])["erro"],"acesso_nao_autorizado")
            self.assertEqual(x["headers"]["Cache-Control"],"no-store, private")

    def test_gate_orcamento_impede_qualquer_consulta(self):
        with patch.dict(os.environ,{"NIVON_MVP_TOKEN_SHA256":SHA,
                                    "NIVON_MVP_BQ_READ_APPROVED":"false"},clear=True):
            state={}
            body=b"".join(mvp.app({"PATH_INFO":"/api/v1/resumo","REQUEST_METHOD":"GET",
                "QUERY_STRING":"","HTTP_AUTHORIZATION":"Bearer "+TOKEN},
                lambda s,h:state.update(status=s)))
        self.assertEqual(state["status"],"503 Service Unavailable")
        self.assertIn(b"nao_aprovada",body)

    def test_limite_proveniencia_sem_agregar_modalidades(self):
        f=FakeCalls()
        out=mvp.montar_resumo(projeto="nivon-data",dataset="nivon_raw",
            mes="2025-12",passagem="panama",instante=NOW,
            ler_ferrovia=f.rail,ler_maritimo=f.sea)
        self.assertEqual(out["estado"],"CONSULTAS_REAIS_LIMITADAS")
        self.assertEqual(out["consultas_reais_confirmadas"],2)
        self.assertEqual(len(f.calls),2)
        self.assertEqual(f.calls[0][1]["max_bytes_billed"],50_000_000)
        self.assertEqual(f.calls[1][1]["max_bytes_billed"],50_000_000)
        self.assertFalse(out["homologado_para_decisoes_comerciais"])
        self.assertNotIn("arquivos_sha256",out["fontes"]["ferrovia"])
        self.assertFalse(out["fontes"]["maritimo"]["volume_realizado_confirmado"])
        self.assertEqual(out["fontes"]["maritimo"]["transitos_ais_reportados"],11)

    def test_erro_individual_sem_revelar_segredos(self):
        f=FakeCalls(fail="rail")
        out=mvp.montar_resumo(projeto="nivon-data",dataset="nivon_raw",
            mes="2025-12",passagem="panama",instante=NOW,
            ler_ferrovia=f.rail,ler_maritimo=f.sea)
        self.assertEqual(out["estado"],"DADOS_PARCIAIS")
        self.assertEqual(out["consultas_reais_confirmadas"],1)
        self.assertEqual(out["erros"][0]["classe_erro"],"ValueError")
        self.assertNotIn("/hidden/",json.dumps(out))

    def test_anti_injecao_e_periodo_futuro(self):
        for q in ("mes=2025-12&passagem=panama&extra=1",
                  "mes=2025-12&mes=2025-11",
                  "mes=2026-10&passagem=suape",
                  "mes=2025-13"):
            with self.subTest(q=q),self.assertRaises(mvp.ErroTerminal):
                mvp._params(q)
        with self.assertRaises(mvp.ErroTerminal):
            mvp.montar_resumo(projeto="nivon-data",dataset="nivon_raw",
                mes="2027-01",passagem="panama",instante=NOW)
        with self.assertRaises(mvp.ErroTerminal):
            mvp.montar_resumo(projeto="nivon-data;DROP",dataset="nivon_raw",
                mes="2025-12",passagem="panama",instante=NOW)

    def test_assets_e_csp_locais(self):
        index=request("/")
        self.assertEqual(index["status"],"200 OK")
        self.assertIn(b"NIVON",index["body"])
        self.assertIn("Content-Security-Policy",index["headers"])
        js=request("/terminal.js")
        self.assertEqual(js["status"],"200 OK")
        self.assertIn(b"textContent",js["body"])
        css=request("/terminal.css")
        self.assertEqual(css["status"],"200 OK")
        self.assertIn(b"--green",css["body"])

    def test_get_validado_sem_inventar_dado(self):
        falso={
            "consultas_reais_confirmadas":1,"estado":"DADOS_PARCIAIS",
            "fontes":{"ferrovia":{"estado":"REVISAO_ATUAL"}},
            "corte":"2026-10-25T21:00:00+00:00"
        }
        with patch.object(mvp,"montar_resumo",return_value=falso):
            x=request("/api/v1/resumo",token=TOKEN,query="mes=2025-12&passagem=panama")
        self.assertEqual(x["status"],"200 OK")
        self.assertEqual(json.loads(x["body"])["estado"],"DADOS_PARCIAIS")

if __name__=="__main__":
    unittest.main()
