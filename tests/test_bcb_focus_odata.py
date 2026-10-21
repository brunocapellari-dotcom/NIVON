"""Sem rede: testes Focus BCB, OData e isolamento de previsões."""
import json
import unittest
from datetime import datetime, timezone
from urllib.parse import urlsplit

from nivon.bcb_focus_odata import planejar_focus, normalizar_focus, ErroFocus
from nivon.apis_gratuitas_execucao import consultar_focus, ErroAPIPublica

NOW = datetime(2026, 10, 21, 18, 0, tzinfo=timezone.utc)


def resultado():
    return {"value": [{"Indicador": "Câmbio", "Data": "2026-10-20",
                       "DataReferencia": "2027", "Media": 5.10, "Mediana": 5.08},
                      {"Indicador": "Câmbio", "Data": "2026-10-19",
                       "DataReferencia": 2028, "Media": 5.23, "Mediana": 5.20}]}


class Resp:
    status = 200
    headers = {"Content-Type": "application/json"}
    def __init__(self, url, body):
        self.url, self.body = url, body
    def __enter__(self): return self
    def __exit__(self, *a): return False
    def geturl(self): return self.url
    def read(self, n): return self.body[:n]


class Abridor:
    def __init__(self, body):
        self.calls = []
        self.body = body
    def open(self, req, timeout):
        self.calls.append(req.full_url)
        return Resp(req.full_url, self.body)


class TestBCBFocus(unittest.TestCase):
    def test_planejador_filtra_indicador_e_datas(self):
        url = planejar_focus(indicador="Câmbio", inicio="2026-10-19",
                             fim="2026-10-20", max_itens=100)
        self.assertTrue(url.startswith("https://olinda.bcb.gov.br/"))
        self.assertIn("ExpectativasMercadoAnuais", url)
        self.assertIn("%24filter=", url)
        for wrong in ["Câmbio' OR 1=1", "Soja", ""]:
            with self.assertRaises(ErroFocus):
                planejar_focus(indicador=wrong, inicio="2026-10-19",
                               fim="2026-10-20")
        with self.assertRaises(ErroFocus):
            planejar_focus(indicador="Câmbio", inicio="2025-01-01",
                           fim="2026-10-20")

    def test_consulta_unica_e_projecao_nao_valor_observado(self):
        a = Abridor(json.dumps(resultado()).encode())
        r = consultar_focus(indicador="Câmbio", inicio="2026-10-19",
                            fim="2026-10-20", max_itens=100,
                            executar=True, abridor=a, instante=NOW)
        self.assertEqual(len(a.calls), 1)
        self.assertEqual(urlsplit(a.calls[0]).hostname, "olinda.bcb.gov.br")
        self.assertEqual(r["dados"]["observacoes"][0]["ano_alvo"], "2027")
        self.assertEqual(r["dados"]["observacoes"][0]["media"], "5.1")
        self.assertEqual(r["dados"]["observacoes"][0]["unidade"], "BRL_POR_USD_ESPERADO")
        self.assertEqual(r["dados"]["observacoes"][0]["coleta"], "2026-10-21T18:00:00+00:00")
        self.assertFalse(r["dados"]["apto_backtest_asof"])
        self.assertFalse(r["dados"]["publicacao_comprovada"])
        self.assertIn("PROJECAO", r["dados"]["observacoes"][0]["natureza"])

    def test_default_deny_e_nao_chamar_http(self):
        a = Abridor(json.dumps(resultado()).encode())
        with self.assertRaises(PermissionError):
            consultar_focus(indicador="Câmbio", inicio="2026-10-19",
                            fim="2026-10-20", abridor=a)
        self.assertFalse(a.calls)

    def test_nao_permitir_paginacao_ignorada(self):
        doc = resultado()
        doc["@odata.nextLink"] = "pagina-2"
        with self.assertRaises(ErroFocus):
            normalizar_focus(json.dumps(doc).encode(), indicador="Câmbio",
                             inicio="2026-10-19", fim="2026-10-20",
                             max_itens=100, coletado_em="2026-10-21T18:00:00Z")

    def test_datas_falsas_medias_nao_finitas_e_indicadores_trocados(self):
        for obj in (
            {"value": [{"Indicador": "Câmbio", "Data": "2026-10-22",
                        "DataReferencia": "2027", "Media": 5, "Mediana": 5}]},
            {"value": [{"Indicador": "Selic", "Data": "2026-10-20",
                        "DataReferencia": "2027", "Media": 13, "Mediana": 13}]},
            {"value": [{"Indicador": "Câmbio", "Data": "2026-10-20",
                        "DataReferencia": "2027", "Media": float("nan"), "Mediana": 5}]},
        ):
            with self.subTest(obj=obj), self.assertRaises(ErroFocus):
                normalizar_focus(json.dumps(obj).encode(), indicador="Câmbio",
                                 inicio="2026-10-19", fim="2026-10-20",
                                 max_itens=100, coletado_em="2026-10-21T18:00:00Z")

    def test_nao_aceitar_chave_json_duplicada(self):
        raw = b'{"value":[],"value":[]}'
        with self.assertRaises(ErroFocus):
            normalizar_focus(raw, indicador="Câmbio", inicio="2026-10-19",
                             fim="2026-10-20", max_itens=100,
                             coletado_em="2026-10-21T18:00:00Z")


if __name__ == "__main__":
    unittest.main()
