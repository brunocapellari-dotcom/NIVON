"""Aceite Cloud Run privado: não consultar GCP nem autenticar em testes."""
import json
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace
import unittest

from nivon.terminal_live_acceptance import (
    AceiteBloqueado, aceitar, validar_url, validar_payload, validar_portal, metadados_e_token,
)

NOW = datetime(2026,10,25,23,0,tzinfo=timezone.utc)
URL = "https://nivon-terminal-123456789.southamerica-east1.run.app"

def fixtures():
    serie = [{
        "ano": ano, "registros": 120, "toneladas_uteis": "10000",
        "ultima_competencia": str(ano) + ("-08" if ano == 2026 else "-12"),
        "parcial": ano == 2026,
    } for ano in range(2006,2027)]
    return {"estado":"ANTT_SERIE_OBSERVADA_DECLARADA",
      "natureza":"OBSERVADO_DECLARADO", "status_publicacao":"PREVIA_PRIVADA",
      "homologacao_editorial":False,"soma_multimodal_permitida":False,
      "point_in_time_historico":False,"fonte":"ANTT/SIADE — transporte ferroviario",
      "serie":serie,"anos":21,"registros_acumulados":2520,
      "tu_acumuladas":"210000","ultima_competencia":"2026-08",
      "ultima_coleta_utc":"2026-10-25T20:00:00+00:00",
      "bytes_processados_ultimo_job":3123}

class Response:
    def __init__(self,body,mime,url):
        self.payload=body
        self.status=200
        self.headers={"Content-Type":mime}
        self.url=url
    def __enter__(self):return self
    def __exit__(self,*args):return False
    def geturl(self):return self.url
    def read(self,n):return self.payload[:n]

class Opener:
    def __init__(self,body=None,redirect=False):
        self.urls=[]
        self.body=body or fixtures()
        self.redirect=redirect
    def open(self,req,timeout):
        self.urls.append(req.full_url)
        path=req.full_url.split(".run.app",1)[1]
        if path=="/healthz":
            data=b'{"estado":"PROCESSO_ATIVO"}'
            mime="application/json"
        elif path=="/":
            data=b'<html>NIVON Carregando dados reais</html>'
            mime="text/html"
        elif path=="/portal":
            data=b'<html>NIVON Portal operacional</html>'
            mime="text/html"
        elif path=="/readyz":
            data=b'{"status":"PAINEL_PRIVADO_COM_DADOS_REAIS"}'
            mime="application/json"
        elif path=="/api/v1/painel":
            data=json.dumps({
                "schema":"nivon.portal.interno.v1",
                "modo":"INTERNO_SHADOW",
                "estado":"DADOS_REAIS_EM_REVISAO_INTERNA_NAO_HOMOLOGADOS",
                "frescor_snapshot":"ATUAL",
                "origem_terminal":"GCS_PRIVADO_COM_SHA256",
                "snapshot_sha256":"a"*64,
                "go_live_publico":False,
                "publicavel":False,
                "redistribuicao_autorizada":False,
                "precos_homologados":False,
                "fontes_consultadas":["ANTT_SIADE_ORIGEM_DESTINO","LINEUP_IMBITUBA"],
                "indicadores":[{"publicavel":False},{"publicavel":False}],
                "gerado_em":"2026-10-25T20:00:00+00:00",
            }).encode()
            mime="application/json"
        else:
            data=json.dumps(self.body).encode()
            mime="application/json"
        return Response(data,mime,req.full_url+"/redirect" if self.redirect else req.full_url)

class TestLiveAcceptance(unittest.TestCase):
    def test_e2e_tres_rotas_somente_get_sem_fabricar(self):
        op=Opener()
        report=aceitar(URL,"placeholder-not-real",opener=op,now=NOW)
        self.assertEqual(report["estado"],"VALIDACAO_PRIVADA_TECNICA_COMPLETA")
        self.assertEqual(report["ultima_competencia"],"2026-08")
        self.assertFalse(report["go_live_publico"])
        self.assertEqual(len(op.urls),6)
        self.assertTrue(report['portal_privado_gcs_verificado'])
        self.assertEqual(report['indicadores_gcs'],2)

    def test_urls_estritas_e_sem_redirecionamento(self):
        for url in ("https://evil.example","http://"+URL[8:],URL+"/another",
                    URL+"/?a=1","https://nivon-terminal-123.southamerica-east1.run.app.evil.com",
                    "https://user:pass@nivon-terminal-123.a.run.app"):
            with self.subTest(url=url),self.assertRaises(AceiteBloqueado):
                validar_url(url)
        with self.assertRaises(AceiteBloqueado):
            aceitar(URL,"t",opener=Opener(redirect=True),now=NOW)

    def test_invalidade_de_payload_nunca_e_aceita(self):
        for key,value in [
            ("estado","SINTETICO"),
            ("fonte","simulado"),
            ("homologacao_editorial",True),
            ("soma_multimodal_permitida",True),
            ("anos",99),("registros_acumulados",0),
            ("tu_acumuladas","0"),("ultima_competencia","2027-01"),
            ("bytes_processados_ultimo_job",250000001),
        ]:
            with self.subTest(key=key),self.assertRaises(AceiteBloqueado):
                doc=fixtures();doc[key]=value
                validar_payload(b'{"estado":"PROCESSO_ATIVO"}',
                                b'<html>NIVON Carregando dados reais</html>',
                                json.dumps(doc).encode(),now=NOW)

    def test_verificacao_gcp_metadados_iam_e_token_sem_rede(self):
        service={"metadata":{"name":"nivon-terminal","labels":{"nivon-component":"terminal"}},
                 "spec":{"template":{"spec":{"serviceAccountName":"exec@nivon-data.iam.gserviceaccount.com"}}},
                 "status":{"url":URL,"conditions":[{"type":"Ready","status":"True"}]}}
        policy={"bindings":[{"role":"roles/run.invoker",
                            "members":["serviceAccount:ci@nivon-data.iam.gserviceaccount.com"]}]}
        def fake_run(args,**kw):
            if "get-iam-policy" in args:
                out=json.dumps(policy)
            elif "describe" in args:
                out=json.dumps(service)
            else:
                out="header.payload.signature" * 6
            return SimpleNamespace(stdout=out,stderr="",returncode=0)
        url,token=metadados_e_token(run=fake_run)
        self.assertEqual(url,URL)
        self.assertGreater(len(token),64)
        policy["bindings"][0]["members"].append("allUsers")
        with self.assertRaises(AceiteBloqueado):
            metadados_e_token(run=fake_run)

    def test_portal_ausente_ou_nao_confiavel_impede_aceite(self):
        with self.assertRaises(AceiteBloqueado):
            validar_portal(b'{"status":"SNAPSHOT_INDISPONIVEL"}',
                           b'<html>NIVON</html>',
                           b'{"estado":"fixture"}',now=NOW)
        with self.assertRaises(AceiteBloqueado):
            aceitar(URL,"token",opener=Opener(redirect=True),now=NOW)

    def test_fluxo_de_publicacao_so_aprovado_manualmente(self):
        root=Path(__file__).resolve().parents[1]
        w=(root/".github/workflows/nivon-terminal-go-live.yml").read_text()
        self.assertIn("python -m nivon.terminal_live_acceptance",w)
        self.assertIn("github.event_name == 'workflow_dispatch'",w)
        self.assertIn("NIVON_GCP_COST_REVIEWED",w)
        self.assertNotIn("--allow-unauthenticated",w)


if __name__=="__main__":
    unittest.main()
