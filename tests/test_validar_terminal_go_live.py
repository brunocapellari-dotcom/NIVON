"""Aceite E2E sem Cloud externo: IAM privado, fonte real e anti-vazamento."""
import json
import unittest
from datetime import datetime, timezone

from nivon.validar_terminal_go_live import validar, ErroAceite
from nivon.terminal_web import interpretar_serie
from test_terminal_web import rows, NOW

BASE_URL="https://nivon-terminal-abc-def.a.run.app"
TOKEN="token-simulado-apenas-para-contrato-de-teste"
DOC=interpretar_serie(rows(), ultimo_ano=2026, agora=NOW)


def fake_http(url, *, token=None, an_status=403, dados=None, cache="no-store"):
    if token is None:
        return an_status, {}, b""
    if url.endswith("/healthz"):
        return 200, {"Content-Type":"application/json"},b'{"estado":"PROCESSO_ATIVO"}'
    return (200, {"Content-Type":"application/json","Cache-Control":cache},
            json.dumps(DOC if dados is None else dados).encode())


class TestAceiteGoLive(unittest.TestCase):
    def executar(self, *, an_status=403, dados=None, cache="no-store"):
        def transporte(url, *, token=None):
            return fake_http(url,token=token,an_status=an_status,dados=dados,cache=cache)
        return validar(url=BASE_URL,executar=True,token=TOKEN,
                       transporte=transporte,agora=NOW)

    def test_plano_por_padrao_nao_usa_rede(self):
        chamadas=[]
        out=validar(url=BASE_URL,transporte=lambda **kw:chamadas.append(kw))
        self.assertEqual(out["estado"],"PLANO_SEM_REDE")
        self.assertEqual(chamadas,[])
        self.assertFalse(out["go_live_interno_validado"])

    def test_dados_reais_iam_privado_e_sem_homologacao_total(self):
        out=self.executar()
        self.assertTrue(out["go_live_interno_validado"])
        self.assertFalse(out["go_live_integral_nivon"])
        self.assertEqual(out["mutacoes_cloud_executadas"],0)
        self.assertEqual(out["fonte"]["anos"],21)
        self.assertEqual(out["fonte"]["ultima_competencia"],"2026-08")
        self.assertFalse(out["fonte"]["homologacao_editorial"])

    def test_anonimo_nao_pode_acessar_terminal(self):
        with self.assertRaisesRegex(ErroAceite,"anonimo"):
            self.executar(an_status=200)

    def test_serie_sintetica_parcial_ou_futura_nao_e_publicada(self):
        doc=json.loads(json.dumps(DOC))
        doc["serie"].pop(8)
        with self.assertRaises(ErroAceite):
            self.executar(dados=doc)
        doc=json.loads(json.dumps(DOC))
        doc["serie"][-1]["ultima_competencia"]="2026-12"
        doc["ultima_competencia"]="2026-12"
        with self.assertRaises(ErroAceite):
            self.executar(dados=doc)

    def test_divergencia_soma_uf_e_status_canonico_bloqueia(self):
        doc=json.loads(json.dumps(DOC))
        doc["tu_acumuladas"]="210001"
        with self.assertRaises(ErroAceite):
            self.executar(dados=doc)
        doc=json.loads(json.dumps(DOC))
        doc["homologacao_editorial"]=True
        with self.assertRaises(ErroAceite):
            self.executar(dados=doc)
        doc=json.loads(json.dumps(DOC))
        doc["soma_multimodal_permitida"]=True
        with self.assertRaises(ErroAceite):
            self.executar(dados=doc)

    def test_cabecalho_de_cache_inseguro_bloqueia(self):
        with self.assertRaisesRegex(ErroAceite,"insegura"):
            self.executar(cache="public,max-age=86400")

    def test_token_ausente_ou_invalido_antecede_consultas(self):
        calls=[]
        with self.assertRaisesRegex(ErroAceite,"token"):
            validar(url=BASE_URL,executar=True,token="a",
                    transporte=lambda **kw:calls.append(kw))
        self.assertEqual(calls,[])

    def test_url_fora_do_google_cloud_bloqueada_antes_de_rede(self):
        urls=("https://evil.example.com","http://nivon-terminal-abc.a.run.app",
              "https://nivon-terminal-abc.a.run.app/other",
              "https://nivon-terminal-abc.a.run.app@evil.example.com",
              "https://nivon-terminal-abc.a.run.app:8080",
              "https://nivon-terminal-abc.a.run.app?token=abc")
        for url in urls:
            with self.subTest(url=url),self.assertRaises(ErroAceite):
                validar(url=url,executar=True,token=TOKEN)

    def test_cli_default_nao_exige_token_nem_http(self):
        from contextlib import redirect_stdout
        from io import StringIO
        from nivon.validar_terminal_go_live import main
        result=StringIO()
        with redirect_stdout(result):
            self.assertEqual(main(["--url",BASE_URL]),0)
        self.assertFalse(json.loads(result.getvalue())["go_live_interno_validado"])


if __name__=="__main__":
    unittest.main()
