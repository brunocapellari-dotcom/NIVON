"""Testes inteiramente offline: APIs públicas pontuais INMET e CPTEC/INPE."""
import io
import json
import unittest
from urllib.error import HTTPError

from nivon.inmet_estacoes_publicas import (
    ErroCatalogoINMET, consultar_catalogo, normalizar_catalogo, preparar_consulta,
)
from nivon.cptec_previsao_brasilapi import (
    ErroPrevisaoCPTEC, consultar_previsao, normalizar_previsao,
    preparar_consulta as preparar_cptec,
)


class Response:
    status = 200

    def __init__(self, raw):
        self.buffer = io.BytesIO(raw)

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def read(self, n):
        return self.buffer.read(n)


class Transporte:
    def __init__(self, raw, error=None):
        self.raw, self.error, self.calls, self.request = raw, error, 0, None

    def open(self, request, timeout):
        self.calls += 1
        self.request = request
        if self.error:
            raise HTTPError(request.full_url, self.error,
                            "não revelar URL upstream", {}, None)
        return Response(self.raw)


ESTACOES = json.dumps([
    {"CD_ESTACAO":"A908", "SG_ESTADO":"MT", "DC_NOME":"AGUA BOA",
     "VL_LATITUDE":"-14.01638888", "VL_LONGITUDE":"-52.21166666",
     "CD_SITUACAO":"Pane", "DT_INICIO_OPERACAO":"2006-12-15T21:00:00.000-03:00"},
    {"CD_ESTACAO":"A001", "SG_ESTADO":"DF", "DC_NOME":"BRASILIA",
     "VL_LATITUDE":"-15.78", "VL_LONGITUDE":"-47.93",
     "CD_SITUACAO":"Operante"}
]).encode()

PREVISAO = json.dumps({
    "cidade": "São Paulo", "estado": "SP", "atualizado_em":"2026-10-21",
    "clima":[
        {"data":"2026-10-21","condicao":"pc","min":18,"max":29,"indice_uv":0},
        {"data":"2026-10-22","condicao":"pn","min":19,"max":30,"indice_uv":8},
    ]
}).encode()


class TestCatalogoINMET(unittest.TestCase):
    def test_catalogo_realista_tem_metadados_sem_observacoes(self):
        rows = normalizar_catalogo(ESTACOES, tipo="T")
        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[0]["codigo_estacao"], "A908")
        self.assertEqual(rows[0]["uf"], "MT")
        self.assertEqual(rows[0]["situacao_reportada"], "Pane")
        self.assertFalse(rows[0]["observacao_meteorologica"])
        self.assertFalse(rows[0]["homologado"])
        self.assertFalse(rows[0]["publicavel"])

    def test_rede_opt_in_e_host_allowlist(self):
        req = preparar_consulta("T")
        self.assertEqual(req.full_url, "https://apitempo.inmet.gov.br/estacoes/T")
        t = Transporte(ESTACOES)
        with self.assertRaises(PermissionError):
            consultar_catalogo(transporte=t)
        self.assertEqual(t.calls, 0)
        rows = consultar_catalogo(habilitar_rede=True, transporte=t)
        self.assertEqual(len(rows), 2)
        self.assertEqual(t.calls, 1)

    def test_rejeita_tipo_payload_malicioso_ou_incompleto(self):
        with self.assertRaises(ErroCatalogoINMET):
            preparar_consulta("../../../segredo")
        with self.assertRaises(ErroCatalogoINMET):
            normalizar_catalogo(b'{"error":"proxy"}', tipo="T")
        with self.assertRaises(ErroCatalogoINMET):
            normalizar_catalogo(b'<html>Proxy</html>', tipo="T")
        x = json.loads(ESTACOES)
        x[1]["CD_ESTACAO"] = x[0]["CD_ESTACAO"]
        with self.assertRaises(ErroCatalogoINMET):
            normalizar_catalogo(json.dumps(x).encode(), tipo="T")

    def test_http_error_nao_expoe_upstream(self):
        t=Transporte(b"", error=403)
        with self.assertRaises(ErroCatalogoINMET) as c:
            consultar_catalogo(habilitar_rede=True, transporte=t)
        self.assertNotIn("apitempo.inmet.gov.br", str(c.exception))


class TestCPTECPontual(unittest.TestCase):
    def test_previsao_natureza_projetada_sem_ibge_e_uv_suspeito(self):
        r=normalizar_previsao(PREVISAO, codigo_cptec=244, dias=3)
        self.assertEqual(r["fonte_primaria"], "CPTEC/INPE")
        self.assertEqual(r["provedor"], "BrasilAPI")
        self.assertEqual(r["codigo_cptec"], 244)
        self.assertIsNone(r["codigo_ibge"])
        self.assertEqual(len(r["previsoes"]), 2)
        self.assertEqual(r["previsoes"][0]["natureza"], "PROJETADO")
        self.assertIsNone(r["previsoes"][0]["indice_uv_reportado"])
        self.assertEqual(r["previsoes"][1]["indice_uv_reportado"], 8)
        self.assertFalse(r["frescor_verificado"])
        self.assertFalse(r["publicavel"])

    def test_somente_endpoint_pontual_e_seis_dias(self):
        req=preparar_cptec(codigo_cptec=244, dias=3)
        self.assertEqual(req.full_url,
                         "https://brasilapi.com.br/api/cptec/v1/clima/previsao/244/3")
        for cid, days in ((0,1),(1234567,2),(244,7),(True,3),(244,True)):
            with self.subTest(cid=cid,days=days):
                with self.assertRaises(ErroPrevisaoCPTEC):
                    preparar_cptec(codigo_cptec=cid,dias=days)

    def test_rede_desligada_ate_opt_in(self):
        t=Transporte(PREVISAO)
        with self.assertRaises(PermissionError):
            consultar_previsao(codigo_cptec=244,transporte=t)
        self.assertEqual(t.calls,0)
        r=consultar_previsao(codigo_cptec=244,habilitar_rede=True,transporte=t)
        self.assertEqual(r["cidade"], "São Paulo")
        self.assertEqual(t.calls,1)

    def test_rejeita_dados_invalidos_mesmo_http_200(self):
        for doc in (
            {"error":"denied"},
            {"cidade":"X", "estado":"SP", "atualizado_em":"2026-10-21",
             "clima":[{"data":"2026-10-21","condicao":"pc","min":32,"max":10}]},
            {"cidade":"X", "estado":"SP", "atualizado_em":"2026-10-21",
             "clima":[{"data":"2026-10-21","condicao":"pc","min":21,"max":29},
                      {"data":"2026-10-21","condicao":"pc","min":21,"max":29}]},
        ):
            with self.subTest(case=doc):
                with self.assertRaises(ErroPrevisaoCPTEC):
                    normalizar_previsao(json.dumps(doc).encode(),codigo_cptec=244,dias=3)

    def test_http_error_sem_spill(self):
        t=Transporte(b"",error=429)
        with self.assertRaises(ErroPrevisaoCPTEC) as c:
            consultar_previsao(codigo_cptec=244,habilitar_rede=True,transporte=t)
        self.assertNotIn("brasilapi.com.br",str(c.exception))


if __name__=="__main__":
    unittest.main()
