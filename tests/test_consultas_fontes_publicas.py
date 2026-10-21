"""Testes dos adaptadores CFTC, INPE e ANTT com respostas sintéticas.

Não faz download real nem registra indicadores atuais.
"""
import json
from datetime import datetime, timezone
import unittest

from nivon.cftc_cot_publico import planejar_cot, normalizar_cot, ErroCFTC
from nivon.inpe_queimadas_csv import url_focos_diario, normalizar_focos_diarios, ErroFocosINPE
from nivon.consultas_fontes_publicas import (
    consultar_cftc, consultar_inpe_focos, consultar_antt_trafego,
    ErroConsultaPublica, _adquirir,
)

AGORA = datetime(2026, 10, 21, 19, 0, tzinfo=timezone.utc)


def cftc():
    return [{
        "cftc_contract_market_code": "002602",
        "market_and_exchange_names": "SOYBEANS - CHICAGO BOARD OF TRADE",
        "report_date_as_yyyy_mm_dd": "2026-10-20T00:00:00.000",
        "open_interest_all": "300000",
        "prod_merc_positions_long_all": "82000",
        "prod_merc_positions_short_all": "92000",
        "m_money_positions_long_all": "20000",
        "m_money_positions_short_all": "30000",
    }]


def inpe():
    return ("data_hora_gmt,latitude,longitude,satelite,estado,municipio,bioma,frp,risco_fogo\n"
            "2026-10-20 15:10:00,-12.5,-55.4,NOAA-20,MT,Cidade Teste,Cerrado,12.5,0.8\n").encode()


def ckan():
    return {"success": True, "result": {"count": 1, "results": [{
        "id": "test-dataset", "title": "Volume de Tráfego nas Praças de Pedágio",
        "license_id": "cc-by", "metadata_modified": "2026-10-01T00:00:00",
        "resources": [
            {"format": "CSV", "url": "https://dados.antt.gov.br/dataset/teste/download.csv"},
            {"format": "EXE", "url": "https://malicioso.example/file.exe"},
        ],
    }]}}


class Resposta:
    def __init__(self, url, body, *, mime, status=200, redirect=None):
        self.url, self.body, self.mime, self.status = url, body, mime, status
        self.redirect = redirect
        self.headers = {"Content-Type": mime}

    def __enter__(self): return self
    def __exit__(self, *a): return False
    def geturl(self): return self.redirect or self.url
    def read(self, n): return self.body[:n]


class Abridor:
    def __init__(self, body, mime, *, status=200, redirect=None):
        self.body, self.mime, self.status, self.redirect = body, mime, status, redirect
        self.calls = []

    def open(self, req, timeout):
        self.calls.append(req.full_url)
        self.calls.append(timeout)
        return Resposta(req.full_url, self.body, mime=self.mime,
                        status=self.status, redirect=self.redirect)


class TestConectoresPublicos(unittest.TestCase):
    def test_cftc_planejador_soqL_sem_injecao(self):
        url = planejar_cot(data="2026-10-20", mercado="SOYBEANS", limite=20)
        self.assertIn("72hh-3qpy.json", url)
        self.assertIn("%24where=", url)
        with self.assertRaises(ErroCFTC):
            planejar_cot(data="2026-10-20", mercado="X' OR 1=1", limite=20)
        with self.assertRaises(ErroCFTC):
            planejar_cot(data="2026-10-20", mercado="SOYBEANS", limite=501)

    def test_cftc_consulta_apenas_uma_e_preserva_posicao(self):
        ab = Abridor(json.dumps(cftc()).encode(), "application/json")
        r = consultar_cftc(data="2026-10-20", mercado="SOYBEANS", limite=100,
                           executar=True, abridor=ab, instante=AGORA)
        self.assertEqual(len(ab.calls), 2)
        self.assertEqual(r["dados"]["observacoes"][0]["posicoes_contratos"]["open_interest_all"], 300000)
        self.assertIsNone(r["dados"]["observacoes"][0]["publicacao"])
        self.assertIn("NAO_PRECOS", r["dados"]["observacoes"][0]["natureza"])
        self.assertFalse(r["dados"]["apto_publicacao"])

    def test_cftc_rejeita_data_errada_e_truncamento(self):
        errado = cftc()
        errado[0]["report_date_as_yyyy_mm_dd"] = "2026-10-19T00:00:00.000"
        with self.assertRaises(ErroCFTC):
            normalizar_cot(json.dumps(errado).encode(), data="2026-10-20",
                          mercado="SOYBEANS", limite=100, coletado_em="2026-10-21T19:00:00Z")
        with self.assertRaises(ErroCFTC):
            normalizar_cot(json.dumps(cftc()).encode(), data="2026-10-20",
                          mercado="SOYBEANS", limite=1, coletado_em="2026-10-21T19:00:00Z")

    def test_inpe_url_dia_e_parser_csv_nao_gerar_incendios(self):
        u = url_focos_diario(data="2026-10-20")
        self.assertTrue(u.endswith("focos_diario_br_20261020.csv"))
        a = Abridor(inpe(), "text/csv")
        r = consultar_inpe_focos(data="2026-10-20", executar=True,
                                abridor=a, instante=AGORA)
        self.assertEqual(r["dados"]["quantidade"], 1)
        obs = r["dados"]["observacoes"][0]
        self.assertEqual(obs["frp_mw"], 12.5)
        self.assertEqual(obs["data_referencia"], "2026-10-20")
        self.assertIsNone(obs["publicacao"])
        self.assertTrue(obs["id_gerado_localmente"])
        self.assertIn("NAO_INCENDIO", obs["natureza"])
        self.assertTrue(r["dados"]["arquivo_dia_possivelmente_parcial"])

    def test_inpe_recusa_dia_divergente_e_linha_invalida(self):
        for raw in (
            inpe().replace(b"2026-10-20 15", b"2026-10-19 15"),
            inpe().replace(b"-12.5", b"-192.5"),
            inpe().replace(b",0.8", b",1.9"),
            inpe().replace(b",12.5,", b",nan,"),
        ):
            with self.subTest(raw=raw[:80]), self.assertRaises(ErroFocosINPE):
                normalizar_focos_diarios(payload=raw, data_arquivo="2026-10-20",
                                        coletado_em="2026-10-21T19:00:00Z")

    def test_inpe_csv_sem_registros_nao_prova_zero_fogo(self):
        raw = b"data_hora_gmt,latitude,longitude,satelite\n"
        r = normalizar_focos_diarios(payload=raw, data_arquivo="2026-10-20",
                                    coletado_em="2026-10-21T19:00:00Z")
        self.assertEqual(r["quantidade"], 0)
        self.assertTrue(r["arquivo_dia_possivelmente_parcial"])

    def test_antt_ckan_retorna_referencias_sem_abrir_links(self):
        a = Abridor(json.dumps(ckan()).encode(), "application/json")
        r = consultar_antt_trafego(executar=True, abridor=a, instante=AGORA)
        p = r["dados"]["pacotes_retorno"][0]
        self.assertEqual(p["licenca"], "cc-by")
        self.assertEqual(len(p["recursos_oficiais_candidatos"]), 1)
        self.assertFalse(r["dados"]["apto_publicacao_automatica"])
        self.assertEqual(len(a.calls), 2)

    def test_default_deny_bloqueia_rede(self):
        a = Abridor(b"[]", "application/json")
        with self.assertRaises(PermissionError):
            consultar_cftc(data="2026-10-20", mercado="SOYBEANS", abridor=a)
        self.assertEqual(a.calls, [])

    def test_host_mime_redirect_http_status_e_size_bloqueados(self):
        url = planejar_cot(data="2026-10-20", mercado="SOYBEANS")
        for kw in (
            {"status": 503}, {"mime": "text/html"},
            {"redirect": "https://malicioso.example/file.json"},
        ):
            ab = Abridor(b"[]", kw.get("mime", "application/json"),
                         status=kw.get("status", 200), redirect=kw.get("redirect"))
            with self.subTest(kw=kw), self.assertRaises(ErroConsultaPublica):
                _adquirir(url=url, fonte="cftc", executar=True, abridor=ab, instante=AGORA)
        with self.assertRaises(ErroConsultaPublica):
            _adquirir(url="https://malicioso.example/resource/72hh-3qpy.json?x=1",
                      fonte="cftc", executar=True,
                      abridor=Abridor(b"[]", "application/json"), instante=AGORA)


if __name__ == "__main__":
    unittest.main()
