"""Regressões offline; em nenhuma circunstância imprimem credenciais ou chamam rede."""
import io
import json
import os
import tempfile
import unittest
from unittest.mock import patch
from urllib.error import HTTPError

from nivon.acessos_smoke_privado import executar, main, preflight


class Response:
    status = 200
    def __init__(self, payload):
        self.payload = io.BytesIO(payload)
    def __enter__(self):
        return self
    def __exit__(self, *args):
        return False
    def read(self, n):
        return self.payload.read(n)


class FakeTransport:
    def __init__(self, payload, *, code=None):
        self.payload = payload
        self.request = None
        self.code = code
    def open(self, req, timeout):
        self.request = req
        if self.code is not None:
            raise HTTPError(req.full_url, self.code, "Erro: nunca imprimir segredo", {}, None)
        return Response(self.payload)


class TestAcessosPrivados(unittest.TestCase):
    def test_rede_negada_por_padrao_em_todas_as_fontes(self):
        for fonte in ("usda", "ana", "inmet"):
            with self.subTest(fonte=fonte):
                r = executar(fonte)
                self.assertEqual(r["estado"], "REDE_DESATIVADA")
                self.assertFalse(r["homologado"])

    def test_usda_sem_chave_nao_acessa_rede(self):
        client = FakeTransport(b'[{"commodityCode":"123"}]')
        with patch.dict(os.environ, {"AGROBR_USDA_API_KEY": ""}):
            r = executar("usda", habilitar_rede=True, transporte=client)
        self.assertEqual(r["estado"], "SEGREDO_INDISPONIVEL")
        self.assertIsNone(client.request)

    def test_usda_header_correto_sem_segredo_em_json(self):
        secret = "n" * 40
        client = FakeTransport(b'[{"commodityCode":"0440000","commodityName":"Corn"}]')
        with patch.dict(os.environ, {"AGROBR_USDA_API_KEY": secret}):
            r = executar("usda", habilitar_rede=True, transporte=client)
        self.assertEqual(r["estado"], "AUTENTICACAO_E_SCHEMA_OK")
        self.assertEqual(r["evidencias"]["registros_lidos"], 1)
        self.assertEqual(client.request.get_header("X-api-key"), secret)
        self.assertNotIn(secret, client.request.full_url)
        self.assertNotIn(secret, json.dumps(r))
        self.assertFalse(r["publicavel"])

    def test_usda_chave_recusada_nao_expõe_token(self):
        secret = "s" * 40
        client = FakeTransport(b"", code=403)
        with patch.dict(os.environ, {"AGROBR_USDA_API_KEY": secret}):
            r = executar("usda", habilitar_rede=True, transporte=client)
        self.assertEqual(r["estado"], "CHAVE_RECUSADA")
        self.assertNotIn(secret, json.dumps(r))

    def test_usda_http_200_com_json_de_erro_nao_autentica(self):
        client = FakeTransport(b'[{"error":"API_KEY_INVALID"}]')
        with patch.dict(os.environ, {"AGROBR_USDA_API_KEY": "f"*40}):
            r=executar("usda", habilitar_rede=True, transporte=client)
        self.assertEqual(r["estado"], "SCHEMA_INESPERADO")

    def test_usda_recusa_item_sem_campos_canônicos(self):
        for payload in (
            b'[{"commodityCode":"0440000"}]',
            b'[{"commodityCode":"x","commodityName":"Corn"}]',
            b'[{"commodityCode":"0440000","commodityName":""}]',
            b'[{"commodityCode":"0440000","commodityName":"Corn"}, {"foo":"bar"}]',
            b'[]',
        ):
            with self.subTest(payload=payload):
                client=FakeTransport(payload)
                with patch.dict(os.environ, {"AGROBR_USDA_API_KEY": "f"*40}):
                    result=executar("usda", habilitar_rede=True, transporte=client)
                self.assertEqual(result["estado"], "SCHEMA_INESPERADO")
                self.assertFalse(result["homologado"])

    def test_usda_limiter_e_indisponibilidade_diferenciados(self):
        for http_status, state in (
            (429, "LIMITE_API_ATINGIDO"), (503, "SERVICO_TEMPORARIAMENTE_INDISPONIVEL"),
            (404, "STATUS_HTTP_NAO_VALIDADO"),
        ):
            client=FakeTransport(b"", code=http_status)
            with patch.dict(os.environ, {"AGROBR_USDA_API_KEY": "f"*40}):
                r=executar("usda", habilitar_rede=True, transporte=client)
            self.assertEqual(r["estado"],state)

    def test_usda_200_sem_json_valido_nao_homologa(self):
        client = FakeTransport(b"<html>Invalid Key</html>")
        with patch.dict(os.environ, {"AGROBR_USDA_API_KEY": "f"*40}):
            r = executar("usda", habilitar_rede=True, transporte=client)
        self.assertEqual(r["estado"], "FALHA_REDE_OU_PARSER")

    def test_ana_autenticacao_offline_mock_sem_fuga(self):
        from nivon import ana_hidrowebservice as ana
        with (patch.object(ana, "credenciais_ambiente", return_value=("12345678901","SENHA_SUPERSECRETA")),
              patch.object(ana, "efetuar_request", return_value=b'{"code":200}'),
              patch.object(ana, "extrair_token", return_value="TOKEN_SUPERSECRETO" * 5),
              patch.dict(os.environ, {"NIVON_ANA_ESTACAO":"","NIVON_ANA_DATA_BUSCA":"","NIVON_ANA_ZONA_ESTACAO":""})):
            r = executar("ana", habilitar_rede=True)
        self.assertEqual(r["estado"], "AUTENTICACAO_OK_CONSULTA_PENDENTE")
        self.assertNotIn("SENHA_SUPERSECRETA", json.dumps(r))
        self.assertNotIn("TOKEN_SUPERSECRETO", json.dumps(r))

    def test_ana_estacao_requer_fuso_e_data(self):
        from nivon import ana_hidrowebservice as ana
        with (patch.object(ana, "credenciais_ambiente", return_value=("12345678901","fake")),
              patch.object(ana, "efetuar_request", return_value=b'{}'),
              patch.object(ana, "extrair_token", return_value="x"*60),
              patch.dict(os.environ, {"NIVON_ANA_ESTACAO":"15400000","NIVON_ANA_DATA_BUSCA":"",
                                      "NIVON_ANA_ZONA_ESTACAO":""})):
            r=executar("ana", habilitar_rede=True)
        self.assertEqual(r["estado"], "AUTENTICACAO_OK_CONSULTA_PENDENTE")

    def test_ana_resposta_de_estacao_normalizada_por_qc(self):
        from nivon import ana_hidrowebservice as ana
        rows = [{"utilizar_para_modelo":True}, {"utilizar_para_modelo":False}]
        with (patch.object(ana, "credenciais_ambiente", return_value=("12345678901","fake")),
              patch.object(ana, "efetuar_request", side_effect=[b'{}',b'{}']),
              patch.object(ana, "extrair_token", return_value="x"*60),
              patch.object(ana, "normalizar_adotada", return_value=rows),
              patch.dict(os.environ, {"NIVON_ANA_ESTACAO":"15400000",
                                      "NIVON_ANA_DATA_BUSCA":"2026-08-01",
                                      "NIVON_ANA_ZONA_ESTACAO":"America/Manaus"})):
            r=executar("ana",habilitar_rede=True)
        self.assertEqual(r["estado"], "AUTENTICACAO_E_LEITURA_OK")
        self.assertEqual(r["evidencias"]["medicoes_normalizadas"],2)
        self.assertEqual(r["evidencias"]["medicoes_aprovadas_qc"],1)

    def test_ana_sem_medicoes_nao_declara_leitura_validada(self):
        from nivon import ana_hidrowebservice as ana
        with (patch.object(ana, "credenciais_ambiente", return_value=("12345678901", "fake")),
              patch.object(ana, "efetuar_request", side_effect=[b'{}', b'{}']),
              patch.object(ana, "extrair_token", return_value="x"*60),
              patch.object(ana, "normalizar_adotada", return_value=[]),
              patch.dict(os.environ, {"NIVON_ANA_ESTACAO":"15400000",
                                      "NIVON_ANA_DATA_BUSCA":"2026-08-01",
                                      "NIVON_ANA_ZONA_ESTACAO":"America/Manaus"})):
            r=executar("ana", habilitar_rede=True)
        self.assertEqual(r["estado"], "AUTENTICACAO_OK_SEM_MEDICOES")
        self.assertEqual(r["evidencias"]["medicoes_normalizadas"], 0)
        self.assertFalse(r["homologado"])

    def test_inmet_sem_link_bloqueado(self):
        from nivon import inmet_bdmep as im
        with patch.object(im, "link_privado_do_ambiente", side_effect=im.ErroBDMEP("link ausente")):
            r=executar("inmet",habilitar_rede=True)
        self.assertEqual(r["estado"], "LINK_PRIVADO_AUSENTE_OU_INVALIDO")

    def test_inmet_recebimento_privado_sem_caminho_no_resultado(self):
        from nivon import inmet_bdmep as im
        with tempfile.TemporaryDirectory() as dire:
            with (patch.object(im, "link_privado_do_ambiente", return_value="SEGREDO_URL"),
                  patch.object(im, "receber_bdmep", return_value={
                      "inventario":{"csv":1,"membros":2},"bytes":1234,
                      "caminho_privado":"/segredo/nao_expor.zip", "sha256":"a"*64,
                  }),
                  patch.dict(os.environ, {"NIVON_INMET_DIRETORIO_PRIVADO":dire})):
                r=executar("inmet",habilitar_rede=True)
        self.assertEqual(r["estado"],"ZIP_RECEBIDO_E_INSPECIONADO")
        self.assertNotIn("segredo", json.dumps(r).lower())
        self.assertEqual(r["evidencias"]["csv_no_zip"],1)

    def test_preflight_usda_sem_rede_e_sem_segredo_no_relatorio(self):
        segredo = "V" * 40
        with patch.dict(os.environ, {"AGROBR_USDA_API_KEY": segredo}):
            result = preflight("usda")
        self.assertEqual(result["estado"], "CREDENCIAL_FORMATO_OK_NAO_AUTENTICADA")
        self.assertFalse(result["homologado"])
        self.assertNotIn(segredo, json.dumps(result))

    def test_preflight_usda_recusa_ausente_ou_campo_invalido(self):
        for value in ("", "curta", "a"*40+"\\n"):
            with self.subTest(value_len=len(value)):
                with patch.dict(os.environ, {"AGROBR_USDA_API_KEY": value}):
                    result=preflight("usda")
                self.assertEqual(result["estado"], "SEGREDO_INDISPONIVEL")

    def test_preflight_ana_nao_imprime_identificador_ou_senha(self):
        from nivon import ana_hidrowebservice as ana
        with patch.object(ana, "credenciais_ambiente",
                          return_value=("12345678901", "SECRET_PRIVADO")):
            result=preflight("ana")
        self.assertEqual(result["estado"], "CREDENCIAL_FORMATO_OK_NAO_AUTENTICADA")
        self.assertNotIn("SECRET_PRIVADO",json.dumps(result))
        self.assertNotIn("12345678901",json.dumps(result))

    def test_preflight_inmet_nao_entrega_url_do_bdmeP(self):
        from nivon import inmet_bdmep as im
        private_link = "https://bdmep.inmet.gov.br/$2b$10$TOKEN_PRIVADO_EXEMPLO.zip"
        with patch.object(im, "link_privado_do_ambiente", return_value=private_link):
            result=preflight("inmet")
        self.assertEqual(result["estado"], "CREDENCIAL_FORMATO_OK_NAO_AUTENTICADA")
        self.assertNotIn(private_link,json.dumps(result))

    def test_cli_preflight_nao_dispara_live(self):
        import contextlib
        buf=io.StringIO()
        with (patch.dict(os.environ, {"AGROBR_USDA_API_KEY": "A"*40}),
              patch("nivon.acessos_smoke_privado.executar",
                    side_effect=AssertionError("tentou acessar rede")),
              contextlib.redirect_stdout(buf)):
            exitcode=main(["--fonte", "usda", "--preflight"])
        self.assertEqual(exitcode,0)
        self.assertEqual(json.loads(buf.getvalue())["estado"],
                         "CREDENCIAL_FORMATO_OK_NAO_AUTENTICADA")

    def test_fonte_inexistente_rejeitada(self):
        with self.assertRaises(ValueError):
            executar("outra",habilitar_rede=True)

    def test_cli_sem_live_nao_imprime_credencial(self):
        import contextlib
        buf=io.StringIO()
        with (patch.dict(os.environ,{"AGROBR_USDA_API_KEY":"SEGREDO_SUPERLONGO_9876543210"}),
              contextlib.redirect_stdout(buf)):
            self.assertEqual(main(["--fonte","usda"]),0)
        self.assertEqual(json.loads(buf.getvalue())["estado"],"REDE_DESATIVADA")
        self.assertNotIn("SEGREDO_SUPERLONGO",buf.getvalue())


if __name__ == "__main__":
    unittest.main()
