"""Aceite de go-live: preflight GCP, API autenticada e limites sem rede real."""
import json
import unittest
from datetime import datetime, timezone
from types import SimpleNamespace

from nivon.aceite_golive_terminal import (
    ErroAceite, REQUIRED, avaliar_preflight_cloudrun,
    validar_terminal_privado, main, _url_valida,
)
from nivon.diagnostico_terminal_cloudrun import diagnosticar
from nivon.terminal_web import interpretar_serie

NOW=datetime(2026,10,25,20,tzinfo=timezone.utc)
TOKEN="t"*100
URL="https://nivon-terminal-123abc-southamerica-east1.a.run.app"


def serie():
    rows=[]
    for year in range(2006,2027):
        rows.append({
            "ano":year,"registros":120,
            "tu":"10000","ultima_competencia":f"{year}-"+("08" if year==2026 else "12"),
            "versoes_sha":1,"ultima_coleta":NOW,
        })
    return interpretar_serie(rows,ultimo_ano=2026,agora=NOW)


class Response:
    def __init__(self,data,*,mime="application/json",status=200,headers=None):
        self.status=status
        self.payload=data
        self.headers={
            "Content-Type":mime+"; charset=utf-8",
            "Cache-Control":"no-store",
            "X-Frame-Options":"DENY",
            "X-Content-Type-Options":"nosniff",
        }
        self.headers.update(headers or {})
    def __enter__(self):return self
    def __exit__(self,*a):return False
    def read(self,n):return self.payload[:n]


class Opener:
    def __init__(self,*,payload=None,error_path=None,headers=None):
        self.requests=[]
        self.payload=payload or serie()
        self.error_path=error_path
        self.headers=headers or {}
    def open(self,req,timeout):
        self.requests.append((req.full_url,req.get_header("Authorization"),timeout))
        if req.full_url.endswith("/healthz"):
            return Response(b'{"estado":"PROCESSO_ATIVO"}',headers=self.headers)
        if req.full_url.endswith("/api/v1/ferrovia"):
            if self.error_path:
                raise OSError("IAM-MANAGED-SECRET-WITH-TOKEN")
            return Response(json.dumps(self.payload).encode(),headers=self.headers)
        if req.full_url.endswith("/"):
            return Response(b'<html><title>NIVON</title><meta name="robots" content="noindex"></html>',
                            mime="text/html",headers=self.headers)
        raise AssertionError("unexpected endpoint")


def diag(status=None,existing="AUSENTE",iam="NAO_CONFIGURADO"):
    s={k:"CONFIRMADO" for k in REQUIRED}
    s.update(status or {})
    s["terminal_cloudrun_existente"]=existing
    s["terminal_iam_privado"]=iam
    ok=all(s[k]=="CONFIRMADO" for k in REQUIRED) and (
        existing=="AUSENTE" and iam in ("NAO_CONFIGURADO","AUSENTE")
        or existing=="CONFIRMADO" and iam=="CONFIRMADO"
    )
    return {
        "componentes":s,"metadados_basicos_confirmados":bool(ok),
        "sql_executado":False,"alteracoes_cloud":0,
    }


class TestPreflight(unittest.TestCase):
    def test_metadata_ready_not_a_deployment(self):
        r=avaliar_preflight_cloudrun(diag())
        self.assertEqual(r["status"],"METADADOS_PRONTOS_NAO_E_DEPLOY")
        self.assertEqual(r["total_bloqueios"],0)
        self.assertFalse(r["go_live_aprovado"])
        self.assertFalse(r["deploy_executado"])
        self.assertFalse(r["consumo_bigquery_executado"])

    def test_missing_repo_service_account_and_bq(self):
        state=diag({
            "artifact_repository":"NAO_CONFIGURADO",
            "execution_service_account":"AUSENTE",
            "bigquery_view":"SEM_PERMISSAO",
        })
        r=avaliar_preflight_cloudrun(state)
        self.assertEqual(r["status"],"NO_GO_METADADOS")
        self.assertEqual(r["total_bloqueios"],3)
        self.assertEqual({p["componente"] for p in r["bloqueios"]},
                         {"artifact_repository","execution_service_account",
                          "bigquery_view"})
        self.assertNotIn("@",str(r["bloqueios"]))

    def test_existing_public_cloudrun_blocks(self):
        state=diag(existing="CONFIRMADO",iam="DIVERGENTE")
        r=avaliar_preflight_cloudrun(state)
        self.assertEqual(r["bloqueios"][0]["componente"],"terminal_iam_privado")

    def test_invalid_unrecognized_state_and_fabricated_sql(self):
        for changed in (
            {"componentes":{**diag()["componentes"],"email":"secret"}},
            {"sql_executado":True}, {"alteracoes_cloud":1},
            {"metadados_basicos_confirmados":True,
             "componentes":{**diag()["componentes"],
                            "bigquery_view":"SEM_PERMISSAO"}},
        ):
            d=diag()
            d.update(changed)
            with self.subTest(change=changed),self.assertRaises(ErroAceite):
                avaliar_preflight_cloudrun(d)


class TestSmoke(unittest.TestCase):
    def test_authenticates_three_endpoints_and_minimizes_output(self):
        client=Opener()
        r=validar_terminal_privado(url=URL,token=TOKEN,agora=NOW,opener=client)
        self.assertEqual(r["status"],"SMOKE_PRIVADO_AUTENTICADO_PASSOU")
        self.assertEqual(r["anos"],21)
        self.assertEqual(r["ultima_competencia"],"2026-08")
        self.assertEqual(r["rotas_verificadas"],["/healthz","/api/v1/ferrovia","/"])
        self.assertTrue(r["identidade_iam_foi_aceita"])
        self.assertFalse(r["go_live_final_homologado"])
        self.assertFalse(r["custos_medidos"])
        self.assertFalse(r["publicavel"])
        self.assertNotIn(TOKEN,str(r))
        self.assertNotIn("210000",str(r))
        self.assertEqual(len(client.requests),3)
        self.assertTrue(all(x[1]=="Bearer "+TOKEN and x[2]==12 for x in client.requests))

    def test_reject_public_domains_ip_http_port_query_credentials(self):
        urls=[
            "http://nivon-terminal-abcde.a.run.app",
            "https://nivon-terminal-abcde.a.run.app:444",
            "https://nivon-terminal-abcde.a.run.app@evil.com",
            "https://nivon-terminal-abcde.a.run.app/path",
            "https://nivon-terminal-abcde.a.run.app?token=hello",
            "https://www.vercel.app",
            "https://127.0.0.1",
            "https://evil.nivon-terminal-abcde.a.run.app",
            "https://nivon-terminal-abcde.a.run.app/#fragment",
        ]
        for url in urls:
            with self.subTest(url=url),self.assertRaises(ErroAceite):
                _url_valida(url)

    def test_no_network_without_token(self):
        c=Opener()
        with self.assertRaises(ErroAceite):
            validar_terminal_privado(url=URL,token="",agora=NOW,opener=c)
        self.assertEqual(c.requests,[])

    def test_block_malformed_or_methodologically_incorrect_series(self):
        cases=[
            {"estado":"SINTETICO"},
            {"natureza":"PROJETADO"},
            {"homologacao_editorial":True},
            {"point_in_time_historico":True},
            {"status_publicacao":"PUBLICA"},
            {"ultima_competencia":"2027-12"},
            {"registros_acumulados":0},
            {"anos":99},
        ]
        for patch in cases:
            d=serie()
            d.update(patch)
            with self.subTest(patch=patch),self.assertRaises(ErroAceite):
                validar_terminal_privado(url=URL,token=TOKEN,agora=NOW,
                                         opener=Opener(payload=d))

    def test_block_missing_security_headers(self):
        with self.assertRaisesRegex(ErroAceite,"cabeçalhos"):
            validar_terminal_privado(url=URL,token=TOKEN,agora=NOW,
                opener=Opener(headers={"Cache-Control":"private",
                                      "X-Frame-Options":"ALLOW"}))

    def test_fail_closed_without_leaking_http_errors(self):
        c=Opener(error_path=True)
        with self.assertRaisesRegex(ErroAceite,"não acessível"):
            validar_terminal_privado(url=URL,token=TOKEN,agora=NOW,opener=c)
        self.assertEqual(len(c.requests),2)

    def test_cli_default_is_network_disabled(self):
        from contextlib import redirect_stdout
        from io import StringIO
        stream=StringIO()
        with redirect_stdout(stream):
            rc=main([])
        self.assertEqual(rc,0)
        self.assertFalse(json.loads(stream.getvalue())["rede_executada"])


if __name__=="__main__":
    unittest.main()
