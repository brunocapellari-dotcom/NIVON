"""Teste offline NASA POWER, Open-Meteo forecast/archive e Open-Meteo GloFAS."""
import io
import json
import unittest
from urllib.error import HTTPError

from nivon.hidromet_publico_global import (
    ErroHidrometPublico, consultar_nasa_power, consultar_openmeteo, consultar_glofas,
    planejar_nasa_power, planejar_openmeteo, planejar_glofas,
    normalizar_nasa_power, normalizar_openmeteo, normalizar_glofas,
)


class Response:
    status = 200
    def __init__(self, payload):
        self.data=io.BytesIO(payload)
    def __enter__(self):return self
    def __exit__(self, *_):return False
    def read(self, n):return self.data.read(n)


class FakeHTTP:
    def __init__(self, body, error=None):
        self.body,self.error,self.calls,self.request=body,error,0,None
    def open(self, req, timeout):
        self.calls+=1
        self.request=req
        if self.error:
            raise HTTPError(req.full_url,self.error,req.full_url,{},None)
        return Response(self.body)


POWER=json.dumps({"properties":{"parameter":{
    "PRECTOTCORR":{"20261019":0.0, "20261020":-999},
    "T2M_MAX":{"20261019":33.5, "20261020":32.0},
    "T2M_MIN":{"20261019":18.0, "20261020":19.0}
}}}).encode()

DAILY=json.dumps({
    "daily_units":{"temperature_2m_max":"°C","temperature_2m_min":"°C","precipitation_sum":"mm"},
    "daily":{"time":["2026-10-21","2026-10-22"],"temperature_2m_max":[32.0,33.0],
             "temperature_2m_min":[21.0,20.0],"precipitation_sum":[12.5,0.0]}
}).encode()

FLOOD=json.dumps({
    "latitude":-12.5,"longitude":-55.7,"daily_units":{"river_discharge":"m³/s"},
    "daily":{"time":["2026-10-21","2026-10-22"],"river_discharge":[221.2,180.0]}
}).encode()


class TestNASA(unittest.TestCase):
    def test_plano_pontual_periodo_e_agro(self):
        req=planejar_nasa_power(latitude=-12.5,longitude=-55.7,
                                inicio="2026-10-19",fim="2026-10-20")
        self.assertEqual(req.full_url.split("?")[0],
                         "https://power.larc.nasa.gov/api/temporal/daily/point")
        self.assertIn("community=AG",req.full_url)
        self.assertIn("time-standard=UTC",req.full_url)
        self.assertIn("start=20261019",req.full_url)
        self.assertIn("end=20261020",req.full_url)

    def test_normaliza_sem_confundir_grade_com_estacao(self):
        rows=normalizar_nasa_power(json.loads(POWER),inicio="2026-10-19",
                                  fim="2026-10-20",
                                  parametros=("PRECTOTCORR","T2M_MAX","T2M_MIN"))
        self.assertEqual(rows["natureza"],"GRADE_SATELITE_REANALISE")
        self.assertFalse(rows["observacao_de_estacao"])
        self.assertEqual(len(rows["registros"]),2)
        self.assertEqual(rows["registros"][0]["PRECTOTCORR"],0.0)
        self.assertIsNone(rows["registros"][1]["PRECTOTCORR"])
        self.assertFalse(rows["publicavel"])

    def test_rede_desligada_por_padrao(self):
        mock=FakeHTTP(POWER)
        with self.assertRaises(PermissionError):
            consultar_nasa_power(latitude=-12.5,longitude=-55.7,inicio="2026-10-19",
                                fim="2026-10-20",transporte=mock)
        self.assertEqual(mock.calls,0)
        r=consultar_nasa_power(latitude=-12.5,longitude=-55.7,inicio="2026-10-19",
                              fim="2026-10-20",transporte=mock,habilitar_rede=True)
        self.assertEqual(mock.calls,1)
        self.assertIsNotNone(r["data_coleta"])
        self.assertFalse(r["homologado"])

    def test_limita_periodo_geografia_e_parametros(self):
        for kwargs in (
           {"latitude":-12.5,"longitude":-55.7,"inicio":"2026-01-01","fim":"2026-03-01"},
           {"latitude":-12.5,"longitude":-55.7,"inicio":"2026-10-20","fim":"2026-10-01"},
           {"latitude":100,"longitude":-55.7,"inicio":"2026-10-19","fim":"2026-10-20"},
           {"latitude":-12.5,"longitude":-55.7,"inicio":"2026-10-19","fim":"2026-10-20",
            "parametros":("T2M","UNKNOWN")},
        ):
            with self.subTest(kwargs=kwargs),self.assertRaises(ErroHidrometPublico):
                planejar_nasa_power(**kwargs)

    def test_rejeita_resposta_proxy_sem_valores(self):
        with self.assertRaises(ErroHidrometPublico):
            normalizar_nasa_power({"error":"denied"},inicio="2026-10-19",
                                  fim="2026-10-20",parametros=("T2M_MAX",))


class TestOpenMeteo(unittest.TestCase):
    def test_urls_arquivo_vs_previsao(self):
        p=planejar_openmeteo(latitude=-12.5,longitude=-55.7,modo="previsao",dias=3)
        self.assertEqual(p.full_url.split("?")[0],"https://api.open-meteo.com/v1/forecast")
        self.assertIn("forecast_days=3",p.full_url)
        h=planejar_openmeteo(latitude=-12.5,longitude=-55.7,modo="historico",
                             inicio="2026-08-01",fim="2026-08-05")
        self.assertEqual(h.full_url.split("?")[0],
                         "https://archive-api.open-meteo.com/v1/archive")
        self.assertIn("start_date=2026-08-01",h.full_url)

    def test_temperatura_chuva_e_natureza(self):
        for modo,natureza in (("previsao","PROJETADO"),("historico","REANALISE")):
            with self.subTest(modo=modo):
                out=normalizar_openmeteo(json.loads(DAILY),modo=modo)
                self.assertEqual(out["natureza"],natureza)
                self.assertEqual(len(out["registros"]),2)
                self.assertEqual(out["registros"][0]["precipitation_sum"],12.5)
                self.assertFalse(out["observacao_de_estacao"])

    def test_rede_optin_apenas_uma_requisicao(self):
        transport=FakeHTTP(DAILY)
        with self.assertRaises(PermissionError):
            consultar_openmeteo(latitude=-12.5,longitude=-55.7,transporte=transport)
        self.assertEqual(transport.calls,0)
        r=consultar_openmeteo(latitude=-12.5,longitude=-55.7,
                             habilitar_rede=True,transporte=transport)
        self.assertEqual(len(r["registros"]),2)
        self.assertEqual(transport.calls,1)

    def test_erro_http_nao_vaza_url(self):
        transport=FakeHTTP(b"",error=403)
        with self.assertRaises(ErroHidrometPublico) as ctx:
            consultar_openmeteo(latitude=-12.5,longitude=-55.7,
                                habilitar_rede=True,transporte=transport)
        self.assertNotIn("api.open-meteo.com",str(ctx.exception))

    def test_controle_de_schema_unidades_e_intervalo(self):
        obj=json.loads(DAILY)
        obj["daily_units"]["precipitation_sum"]="inch"
        with self.assertRaises(ErroHidrometPublico):
            normalizar_openmeteo(obj,modo="previsao")
        obj=json.loads(DAILY)
        obj["daily"]["temperature_2m_min"][1]=45
        with self.assertRaises(ErroHidrometPublico):
            normalizar_openmeteo(obj,modo="previsao")
        for dias in (0,8,-1,True):
            with self.assertRaises(ErroHidrometPublico):
                planejar_openmeteo(latitude=-12.5,longitude=-55.7,
                                  modo="previsao",dias=dias)


class TestGloFAS(unittest.TestCase):
    def test_planejar_retorno_de_vazao_nao_cota(self):
        req=planejar_glofas(latitude=-12.5,longitude=-55.7,dias=7)
        self.assertEqual(req.full_url.split("?")[0],"https://flood-api.open-meteo.com/v1/flood")
        self.assertIn("river_discharge",req.full_url)
        out=normalizar_glofas(json.loads(FLOOD))
        self.assertEqual(out["metrica"],"VAZAO_MODELO_M3_S")
        self.assertTrue(out["nao_equivale_nivel_navegavel"])
        self.assertFalse(out["observacao_de_estacao"])
        self.assertEqual(out["natureza"],"PROJETADO")
        self.assertEqual(out["registros"][0]["river_discharge"],221.2)
        self.assertFalse(out["homologado"])

    def test_falha_sem_cobertura_ou_unidade_divergente(self):
        doc=json.loads(FLOOD)
        doc["daily"]["river_discharge"]=[None,None]
        with self.assertRaises(ErroHidrometPublico):
            normalizar_glofas(doc)
        doc=json.loads(FLOOD)
        doc["daily_units"]["river_discharge"]="cm"
        with self.assertRaises(ErroHidrometPublico):
            normalizar_glofas(doc)

    def test_optin_e_prazos(self):
        t=FakeHTTP(FLOOD)
        with self.assertRaises(PermissionError):
            consultar_glofas(latitude=-12.5,longitude=-55.7,transporte=t)
        self.assertEqual(t.calls,0)
        r=consultar_glofas(latitude=-12.5,longitude=-55.7,
                          habilitar_rede=True,transporte=t)
        self.assertEqual(t.calls,1)
        self.assertTrue(r["data_coleta"].endswith("+00:00"))
        for dias in (0,15,True):
            with self.assertRaises(ErroHidrometPublico):
                planejar_glofas(latitude=-12.5,longitude=-55.7,dias=dias)


if __name__=="__main__":
    unittest.main()
