"""NIVON MVP: E2E HTTP no localhost e publicação condicionada.

Fixtures somente sintéticas; não testam IAM, GCP nem licenças reais.
"""
import hashlib
import html
import json
import tempfile
import threading
import unittest
from datetime import datetime, timedelta, timezone
from http.server import ThreadingHTTPServer
from pathlib import Path
from urllib.error import HTTPError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from nivon.mvp_release import ErroReleaseMVP, preparar_edicao
from nivon.mvp_server import _handler, estado_atual

T = datetime(2026, 10, 25, 14, tzinfo=timezone.utc)


def payload(t=T):
    return {
        "schema": "nivon_mvp_edicao_v1",
        "edicao": "NIVON-TURNO-001",
        "gerado_em": t.isoformat(),
        "fontes": {
            "OFICIAL_TESTE": {
                "status_direitos": "APROVADA",
                "operacoes": ["LEITURA", "RESUMO", "PUBLICACAO_DERIVADA"],
            },
        },
        "noticias": [],
        "indicadores": [{
            "fonte_id": "OFICIAL_TESTE", "secao": "CAMBIO",
            "titulo": "Dólar — exemplo sintético", "valor": "R$ 5,00",
            "referencia": (t-timedelta(hours=1)).isoformat(),
            "fonte": "Fonte fictícia exclusiva da suíte",
        }],
        "fretes": [],
    }


class MVPFixture(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        self.file = self.root / "edicao.json"
        self.config = {}
        self.write(payload())

    def write(self, obj):
        data = json.dumps(obj, ensure_ascii=False, sort_keys=True).encode("utf-8")
        self.file.write_bytes(data)
        self.sha = hashlib.sha256(data).hexdigest()
        self.config = {
            "NIVON_RELEASE_APPROVED": "true",
            "NIVON_RELEASE_FILE": str(self.file),
            "NIVON_RELEASE_SHA256": self.sha,
        }
        return data

    def release(self, now=T):
        return preparar_edicao(arquivo=self.file, sha256_aprovado=self.sha,
                              gerado_ate=now)


class TestNIVONRelease(MVPFixture):
    def test_hash_pin_editado_rejeita_antes_de_exibir(self):
        self.file.write_text("{}", encoding="utf-8")
        with self.assertRaises(ErroReleaseMVP):
            self.release()

    def test_nao_pode_publicar_sem_aprovacao_no_ambiente(self):
        self.config["NIVON_RELEASE_APPROVED"] = "false"
        status, ed = estado_atual(self.config, agora=T)
        self.assertIsNone(ed)
        self.assertEqual(status["status"], "PREVIEW_SEM_EDICAO_HOMOLOGADA")

    def test_sem_sha_aprovado_nao_pode_publicar(self):
        self.config["NIVON_RELEASE_SHA256"] = ""
        status, ed = estado_atual(self.config, agora=T)
        self.assertIsNone(ed)
        self.assertEqual(status["status"], "EDICAO_REJEITADA_OU_DESATUALIZADA")

    def test_pacote_valido_aparece_com_sem_envio(self):
        r = self.release()
        self.assertEqual(r["indicadores_incluidos"], 1)
        self.assertEqual(r["fretes_incluidos"], 0)
        self.assertEqual(r["rejeicoes"], [])
        self.assertFalse(r["envio_whatsapp_realizado"])
        self.assertIn("Dólar", r["briefing_texto"])

    def test_arquivo_sintetico_mais_antigo_que_uma_hora_rejeitado(self):
        with self.assertRaises(ErroReleaseMVP):
            self.release(T+timedelta(hours=1, seconds=1))
        self.assertIsNotNone(self.release(T+timedelta(hours=1)))

    def test_edicao_futura_rejeitada(self):
        with self.assertRaises(ErroReleaseMVP):
            self.release(T-timedelta(seconds=1))

    def test_fonte_sem_direito_de_publicacao_rejeita_edicao_toda(self):
        p = payload()
        p["fontes"]["OFICIAL_TESTE"]["operacoes"] = ["LEITURA"]
        self.write(p)
        with self.assertRaises(ErroReleaseMVP):
            self.release()

    def test_indicador_sem_fonte_rejeita_lote_inteiro(self):
        p = payload()
        p["indicadores"].append(dict(p["indicadores"][0], fonte_id="INEXISTENTE"))
        self.write(p)
        with self.assertRaises(ErroReleaseMVP):
            self.release()

    def test_news_antiga_ou_republicada_bloqueia_sem_filtragem_silenciosa(self):
        p = payload()
        p["noticias"] = [{
            "fonte_id": "OFICIAL_TESTE", "titulo": "Documento fictício",
            "resumo": "Notícia inventada apenas para teste",
            "fonte": "Fonte fictícia", "url": "https://example.org/agro/teste",
            "categoria": "MERCADO E COMMODITIES",
            "publicado_em": (T-timedelta(hours=25)).isoformat(),
        }]
        self.write(p)
        with self.assertRaises(ErroReleaseMVP):
            self.release()

    def test_frete_bloqueado_ate_contrato_individual(self):
        p = payload()
        p["fretes"] = [{
            "tipo": "FRETE_ANUNCIADO", "origem": "SORRISO",
            "destino": "RONDONOPOLIS", "valor_rs_t": 100,
        }]
        self.write(p)
        with self.assertRaises(ErroReleaseMVP):
            self.release()

    def test_edicao_sem_dados_nao_apresenta_boletim_inventado(self):
        p = payload()
        p["indicadores"] = []
        self.write(p)
        with self.assertRaises(ErroReleaseMVP):
            self.release()

    def test_json_com_chave_repetida_rejeitado(self):
        bad = (b'{"schema":"x","schema":"y"}')
        self.file.write_bytes(bad)
        with self.assertRaises(ErroReleaseMVP):
            preparar_edicao(
                arquivo=self.file,
                sha256_aprovado=hashlib.sha256(bad).hexdigest(),
                gerado_ate=T,
            )

    def test_symlink_de_arquivo_rejeitado(self):
        link = self.root / "atual.json"
        link.symlink_to(self.file)
        with self.assertRaises(ErroReleaseMVP):
            preparar_edicao(arquivo=link, sha256_aprovado=self.sha,
                            gerado_ate=T)


class TestNIVONHTTP(MVPFixture):
    def setUp(self):
        super().setUp()
        # A API usa relogio corrente; montar uma edição recente sem depender
        # da data absoluta usada nos demais testes.
        self.write(payload(datetime.now(timezone.utc)))
        self.http = ThreadingHTTPServer(("127.0.0.1", 0), _handler(self.config))
        self.thread = threading.Thread(target=self.http.serve_forever,
                                       kwargs={"poll_interval": 0.01}, daemon=True)
        self.thread.start()
        self.addCleanup(self.http.server_close)
        self.addCleanup(self.http.shutdown)

    def fetch(self, path, *, data=None, ctype=None):
        url = f"http://127.0.0.1:{self.http.server_port}{path}"
        headers = {}
        if ctype:
            headers["Content-Type"] = ctype
        request = Request(url, data=data, headers=headers)
        try:
            with urlopen(request, timeout=3) as response:
                return response.status, response.headers, response.read().decode()
        except HTTPError as exc:
            return exc.code, exc.headers, exc.read().decode()

    def test_healthz_e_status_distintos(self):
        code, headers, body = self.fetch("/healthz")
        self.assertEqual(code, 200)
        self.assertEqual(json.loads(body)["status"], "PROCESSO_ATIVO")
        code, headers, body = self.fetch("/api/status")
        self.assertEqual(code, 200)
        self.assertEqual(json.loads(body)["status"], "EDICAO_DISPONIVEL_SOMENTE_CONSULTA")
        self.assertEqual(headers.get("Cache-Control"), "no-store, max-age=0")
        self.assertEqual(headers.get("X-Frame-Options"), "DENY")

    def test_api_edicao_requer_hash_e_aprovacao(self):
        code, _, body = self.fetch("/api/edicao")
        self.assertEqual(code, 200)
        result = json.loads(body)
        self.assertEqual(result["indicadores_incluidos"], 1)
        self.assertFalse(result["envio_whatsapp_realizado"])
        self.config["NIVON_RELEASE_APPROVED"] = "false"
        code, _, body = self.fetch("/api/edicao")
        self.assertEqual(code, 503)
        self.assertFalse(json.loads(body)["edicao_liberada"])

    def test_dashboard_escapa_html_nao_executa_codigo_fonte(self):
        p = payload(datetime.now(timezone.utc))
        p["indicadores"][0]["titulo"] = "<script>window.hacked=1</script>"
        self.write(p)
        code, _, body = self.fetch("/")
        self.assertEqual(code, 200)
        self.assertNotIn("<script>window.hacked=1</script>", body)
        self.assertIn("&lt;script&gt;", body)
        self.assertIn("NIVON", body)

    def test_pagina_sem_release_continua_utilizavel(self):
        self.config["NIVON_RELEASE_APPROVED"] = "false"
        code, _, body = self.fetch("/")
        self.assertEqual(code, 200)
        self.assertIn("PREVIEW_SEM_EDICAO_HOMOLOGADA", body)
        self.assertIn("Planejamento de consultas", body)

    def test_post_ivo_planejamento_real_mas_sem_executar_motores(self):
        data = urlencode({"pergunta": "Analisar soja, clima e fretes"}).encode()
        code, _, html_body = self.fetch(
            "/ivo", data=data, ctype="application/x-www-form-urlencoded")
        self.assertEqual(code, 200)
        self.assertIn("PLANO_OFFLINE_SEM_DADOS_HOMOLOGADOS", html_body)
        self.assertIn("SOJA", html_body)
        self.assertIn("FRETE_RODOVIARIO", html_body)
        self.assertIn("ferramentas_executadas", html_body)

    def test_post_invalido_nao_vira_execucao(self):
        code, _, body = self.fetch("/ivo", data=b"{}", ctype="application/json")
        self.assertEqual(code, 415)
        code, _, body = self.fetch(
            "/ivo", data=urlencode({"pergunta": "x"*451}).encode(),
            ctype="application/x-www-form-urlencoded")
        self.assertEqual(code, 400)
        self.assertEqual(json.loads(body)["status"], "PERGUNTA_INVALIDA")

    def test_rotas_indefinidas_nao_aceitam_query(self):
        code, _, body = self.fetch("/api/edicao?file=../segredo")
        self.assertEqual(code, 404)
        self.assertNotIn(str(self.root), body)

    def test_fail_closed_caso_hash_alterado_apos_geracao(self):
        self.file.write_text('{"adulterado": true}', encoding="utf-8")
        code, _, body = self.fetch("/api/edicao")
        self.assertEqual(code, 503)
        self.assertNotIn(str(self.file), body)


if __name__ == "__main__":
    unittest.main()
