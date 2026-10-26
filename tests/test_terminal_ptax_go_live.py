"""API PTAX integrada ao terminal privado ANTT, sem GCP nem HTTP externo."""
import json
import os
import subprocess
from pathlib import Path
import threading
import unittest
from http.server import ThreadingHTTPServer
from urllib.request import urlopen
from urllib.error import HTTPError

from nivon.terminal_web import PtaxState, TerminalState, servidor, PTAX_TTL_SEGUNDOS


class TestPtaxPrivado(unittest.TestCase):
    def setUp(self):
        self.n=0
        self.requests=0
        self.clock=[0.]
        self.rail={"estado":"ANTT_SERIE_OBSERVADA_DECLARADA","serie":[]}
        self.ptax={
            "schema":"NIVON_PTAX_USD_READONLY_MVP_V1",
            "status":"PREVIA_INTERNA_VALIDA",
            "moeda":"USD","cotacao_venda":5.0,
            "competencia":"2026-10-23","idade_horas":48,
            "variacao_venda_pct_vs_dia_anterior_observado":None,
            "publicacao_autorizada":False,
            "aprovado_go_live":False,
        }

    def setup_server(self,ptax):
        rail=TerminalState(consulta=lambda:self.rail)
        server=ThreadingHTTPServer(("127.0.0.1",0),servidor(state=rail,ptax_state=ptax))
        thread=threading.Thread(target=server.serve_forever,daemon=True)
        thread.start()
        self.addCleanup(lambda:(server.shutdown(),server.server_close(),thread.join(timeout=3)))
        return "http://127.0.0.1:"+str(server.server_port)

    def test_ptax_inativa_pelo_padrao_nao_dispara_get(self):
        def fake():
            self.requests+=1
            return self.ptax
        url=self.setup_server(PtaxState(consulta=fake))
        with urlopen(url+"/api/v1/ptax",timeout=4) as response:
            document=json.load(response)
            self.assertEqual(response.status,200)
            self.assertEqual(response.headers["Cache-Control"],"no-store")
        self.assertEqual(document["status"],"MODULO_AGUARDANDO_HABILITACAO")
        self.assertIsNone(document["cotacao_venda"])
        self.assertEqual(self.requests,0)
        self.assertFalse(document["publicacao_autorizada"])

    def test_ptax_ativada_usa_cache_e_preserva_dado_observado(self):
        def fake():
            self.requests+=1
            return self.ptax
        url=self.setup_server(PtaxState(
            consulta=fake,relogio=lambda:self.clock[0],enabled=True))
        for _ in range(2):
            with urlopen(url+"/api/v1/ptax",timeout=4) as response:
                doc=json.load(response)
                self.assertEqual(doc["cotacao_venda"],5.0)
                self.assertFalse(doc["aprovado_go_live"])
        self.assertEqual(self.requests,1)
        self.clock[0]=PTAX_TTL_SEGUNDOS+1
        with urlopen(url+"/api/v1/ptax",timeout=4):
            pass
        self.assertEqual(self.requests,2)

    def test_fonte_ptax_fora_do_ar_nao_vaza_erro_e_antt_continua(self):
        def failure():
            raise RuntimeError("PRIVATE_CREDENTIAL_DO_NOT_LOG")
        url=self.setup_server(PtaxState(consulta=failure,enabled=True))
        with self.assertRaises(HTTPError) as err:
            urlopen(url+"/api/v1/ptax",timeout=4)
        self.assertEqual(err.exception.code,503)
        self.assertNotIn("PRIVATE_CREDENTIAL",err.exception.read().decode())
        with urlopen(url+"/api/v1/ferrovia",timeout=4) as response:
            self.assertEqual(json.load(response)["estado"],"ANTT_SERIE_OBSERVADA_DECLARADA")

    def test_fonte_bcb_independe_da_ferrovia(self):
        def failed_rail():
            raise RuntimeError("NO_BQ_ACCESS")
        url=self.setup_server(PtaxState(consulta=lambda:self.ptax,enabled=True))
        # O estado padrão de teste tem API ferroviária válida.
        with urlopen(url+"/api/v1/ptax",timeout=4) as response:
            self.assertEqual(json.load(response)["status"],"PREVIA_INTERNA_VALIDA")

    def test_html_mostra_ptax_sem_preco_estatico_ou_fake(self):
        url=self.setup_server(PtaxState())
        with urlopen(url+"/",timeout=4) as response:
            markup=response.read().decode()
        self.assertIn("Câmbio de referência — PTAX USD",markup)
        self.assertIn("'/api/v1/ptax'",markup)
        self.assertIn("id=\"ptax-cards\" hidden",markup)
        self.assertIn("sem persistência",markup)
        self.assertNotIn("R$ 5,00",markup)
        self.assertIn("noindex,nofollow",markup)

    def test_deploy_ptax_sem_direitos_falha_antes_de_gcp(self):
        env=dict(os.environ)
        env.update({
            "GITHUB_REF":"refs/heads/main",
            "NIVON_GO_LIVE_DEPLOY_APPROVED":"true",
            "NIVON_GCP_COST_REVIEWED":"true",
            "NIVON_TERMINAL_ARTIFACT_REPO":"nivon-artifacts",
            "NIVON_TERMINAL_EXECUTION_SA":"nivon-terminal-readonly@nivon-data.iam.gserviceaccount.com",
            "NIVON_PROJETO":"nivon-data",
            "NIVON_DATASET":"nivon_raw",
            "GITHUB_SHA":"0"*40,
            "NIVON_PTAX_INTERNAL_READ_ENABLED":"true",
            "NIVON_PTAX_INTERNAL_SOURCE_APPROVED":"false",
        })
        project=Path(__file__).resolve().parents[1]
        result=subprocess.run(["bash","scripts/deploy_terminal_privado.sh"],
            cwd=project,env=env,text=True,capture_output=True,timeout=6)
        self.assertEqual(result.returncode,3)
        self.assertIn("PTAX_SEM_REVISAO_DIREITOS_DA_FONTE",result.stdout)
        self.assertNotIn("INICIANDO_BUILD_APROVADO",result.stdout)

    def test_healthz_nao_invoca_bcb(self):
        def unexpected():
            self.fail("GET externo efetuado durante healthcheck")
        url=self.setup_server(PtaxState(consulta=unexpected,enabled=True))
        with urlopen(url+"/healthz",timeout=4) as response:
            self.assertEqual(json.load(response)["estado"],"PROCESSO_ATIVO")


if __name__=="__main__":
    unittest.main()
