"""Testes de ponta a ponta (HTTP injetado) sem rede e sem dados reais."""
import hashlib
import json
import unittest
from datetime import datetime, timezone
from urllib.parse import urlsplit

from nivon.apis_gratuitas_execucao import (
    ErroAPIPublica, _obter_json, consultar_open_meteo, consultar_selic,
    consultar_banco_mundial, consultar_ibge_municipios, consultar_nasa_power,
)
from nivon.banco_mundial_indicadores import ErroBancoMundial

NOW = datetime(2026, 10, 21, 16, 0, tzinfo=timezone.utc)


def payload(obj):
    return json.dumps(obj, ensure_ascii=False, allow_nan=True).encode("utf-8")


class Resposta:
    def __init__(self, url, corpo, *, status=200,
                 mime="application/json; charset=utf-8", final=None):
        self.url = final or url
        self.status = status
        self.headers = {"Content-Type": mime}
        self.corpo = corpo

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def geturl(self):
        return self.url

    def read(self, n):
        return self.corpo[:n]


class Abridor:
    def __init__(self, corpo, **resposta):
        self.corpo = corpo
        self.resposta = resposta
        self.urls = []

    def open(self, request, timeout):
        self.urls.append(request.full_url)
        assert timeout <= 15
        return Resposta(request.full_url, self.corpo, **self.resposta)


def clima():
    return {"latitude": -13.0, "longitude": -56.0,
            "timezone": "GMT", "utc_offset_seconds": 0,
            "daily_units": {"time": "iso8601", "precipitation_sum": "mm",
                            "temperature_2m_max": "°C", "temperature_2m_min": "°C"},
            "daily": {"time": ["2026-10-21", "2026-10-22"],
                      "precipitation_sum": [0.0, 5.5],
                      "temperature_2m_max": [34.0, 33.0],
                      "temperature_2m_min": [22.0, 23.0]}}


def wb():
    return [{"page": 1, "pages": 1, "per_page": "100", "total": 2,
             "lastupdated": "2026-10-10"},
            [{"indicator": {"id": "SP.POP.TOTL", "value": "Population, total"},
              "country": {"id": "BR", "value": "Brazil"},
              "countryiso3code": "BRA", "date": "2024", "value": 212000000,
              "obs_status": ""},
             {"indicator": {"id": "SP.POP.TOTL", "value": "Population, total"},
              "country": {"id": "BR", "value": "Brazil"},
              "countryiso3code": "BRA", "date": "2025", "value": None,
              "obs_status": ""}]]


def municipio():
    return [{"id": 5105259, "nome": "Lucas do Rio Verde",
             "regiao-imediata": {"regiao-intermediaria": {"UF": {"sigla": "MT"}}}}]


def power():
    return {"geometry": {"coordinates": [-56.0, -13.0, 300]},
            "properties": {"parameter": {
                "PRECTOTCORR": {"20261019": 0.0, "20261020": 10.2},
                "T2M_MAX": {"20261019": 33.1, "20261020": 32.0},
                "T2M_MIN": {"20261019": 23.1, "20261020": 22.1}}}}


class TestAPIReaisFalsas(unittest.TestCase):
    def test_bloqueio_sem_ativacao_explicita(self):
        a = Abridor(payload(clima()))
        with self.assertRaises(PermissionError):
            consultar_open_meteo(latitude=-13.0, longitude=-56.0, abridor=a)
        self.assertEqual(a.urls, [])

    def test_open_meteo_previsao_https_uma_consulta(self):
        a = Abridor(payload(clima()))
        r = consultar_open_meteo(latitude=-13.0, longitude=-56.0, executar=True,
                                abridor=a, instante=NOW)
        self.assertEqual(len(a.urls), 1)
        self.assertEqual(urlsplit(a.urls[0]).hostname, "api.open-meteo.com")
        self.assertEqual(r["dados"]["quantidade"], 2)
        self.assertEqual(r["dados"]["itens"][0]["precipitation_sum"], 0.0)
        self.assertIsNone(r["dados"]["itens"][0]["publicacao"])
        self.assertFalse(r["dados"]["apto_publicacao_automatica"])
        self.assertEqual(r["aquisição"]["coleta"], "2026-10-21T16:00:00+00:00")
        self.assertNotIn("bytes", r["aquisição"])

    def test_open_meteo_archive_separado_da_previsao(self):
        a = Abridor(payload(clima()))
        r = consultar_open_meteo(latitude=-13.0, longitude=-56.0,
                                tipo="reanalise", inicio="2026-10-21",
                                fim="2026-10-22", executar=True,
                                abridor=a, instante=NOW)
        self.assertEqual(urlsplit(a.urls[0]).hostname, "archive-api.open-meteo.com")
        self.assertEqual(r["dados"]["itens"][0]["observacao_ou_previsao"], "REANALISE_MODELO")

    def test_selic_serie_11_com_data_e_unidade(self):
        a = Abridor(payload([{"data": "20/10/2026", "valor": "0.054266"}]))
        r = consultar_selic(executar=True, abridor=a, instante=NOW)
        self.assertEqual(urlsplit(a.urls[0]).hostname, "api.bcb.gov.br")
        self.assertEqual(r["dados"]["observacoes"][0]["valor_pct_ao_dia"], "0.054266")
        self.assertEqual(r["dados"]["observacoes"][0]["data_referencia"], "2026-10-20")
        self.assertEqual(r["dados"]["observacoes"][0]["unidade"], "PERCENTUAL_AO_DIA")
        self.assertFalse(r["dados"]["apto_publicacao_automatica"])

    def test_worldbank_json_paginado_com_null_e_atualizacao_fonte(self):
        a = Abridor(payload(wb()))
        r = consultar_banco_mundial(indicador="SP.POP.TOTL", inicio=2024, fim=2025,
                                   executar=True, abridor=a, instante=NOW)
        self.assertEqual(urlsplit(a.urls[0]).hostname, "api.worldbank.org")
        self.assertEqual(r["dados"]["numero_observacoes"], 2)
        self.assertEqual(r["dados"]["observacoes"][0]["valor"], "212000000")
        self.assertIsNone(r["dados"]["observacoes"][1]["valor"])
        self.assertEqual(r["dados"]["ultima_atualizacao_fonte"], "2026-10-10")
        self.assertIsNone(r["dados"]["publicacao_individual"])

    def test_worldbank_recusa_pagina_parcial(self):
        o = wb()
        o[0]["pages"] = 2
        with self.assertRaises(ErroBancoMundial):
            consultar_banco_mundial(indicador="SP.POP.TOTL", inicio=2024, fim=2025,
                                   executar=True, abridor=Abridor(payload(o)), instante=NOW)

    def test_ibge_codigo_municipal_oficial_sem_fuzzy(self):
        a = Abridor(payload(municipio()))
        r = consultar_ibge_municipios(executar=True, abridor=a, instante=NOW)
        self.assertEqual(len(a.urls), 1)
        self.assertEqual(r["dados"]["municipios"][0]["codigo_ibge"], "5105259")
        self.assertEqual(r["dados"]["municipios"][0]["uf"], "MT")
        self.assertFalse("publicacao" in r["aquisição"])

    def test_nasa_power_reaproveita_parser_existente(self):
        a = Abridor(payload(power()))
        r = consultar_nasa_power(latitude=-13.0, longitude=-56.0,
                                inicio="2026-10-19", fim="2026-10-20",
                                executar=True, abridor=a, instante=NOW)
        self.assertEqual(len(a.urls), 1)
        self.assertEqual(r["dados"]["numero_dias"], 2)
        self.assertEqual(r["dados"]["registros"][1]["valores"]["PRECTOTCORR"], 10.2)
        self.assertEqual(r["dados"]["registros"][1]["natureza"], "ESTIMADO_REANALISE_GRADE")

    def test_bloquear_http_redirect_html_status_erro_e_tamanho(self):
        args = dict(recurso="bcb_selic", url="https://api.bcb.gov.br/dados/serie/bcdata.sgs.11/dados/ultimos/1?formato=json",
                    executar=True, instante=NOW)
        for kw in ({"status": 503}, {"mime": "text/html"}, {"final": "https://outra.example/teste"}):
            with self.subTest(kw=kw), self.assertRaises(ErroAPIPublica):
                _obter_json(**args, abridor=Abridor(payload([1]), **kw))
        with self.assertRaises(ErroAPIPublica):
            _obter_json(**args, abridor=Abridor(b"x" * 250_001))

    def test_nao_permitir_url_arbitraria_credenciais_ou_protocolo(self):
        for url in ("https://malicioso.example/dados/serie/bcdata.sgs.11/dados/ultimos/1?formato=json",
                    "http://api.bcb.gov.br/dados/serie/bcdata.sgs.11/dados/ultimos/1?formato=json",
                    "https://usuario:senha@api.bcb.gov.br/dados/serie/bcdata.sgs.11/dados/ultimos/1?formato=json",
                    "https://api.bcb.gov.br/qualquer?formato=json"):
            with self.subTest(url=url), self.assertRaises(ErroAPIPublica):
                _obter_json(url, recurso="bcb_selic", executar=True,
                            abridor=Abridor(payload([1])), instante=NOW)

    def test_hash_sha256_rastreavel_sem_inventar_dados(self):
        a = Abridor(payload(clima()))
        r = consultar_open_meteo(latitude=-13.0, longitude=-56.0,
                                executar=True, abridor=a, instante=NOW)
        self.assertEqual(r["aquisição"]["sha256"], hashlib.sha256(a.corpo).hexdigest())
        self.assertEqual(r["dados"]["sha256_original"], r["aquisição"]["sha256"])


if __name__ == "__main__":
    unittest.main()
