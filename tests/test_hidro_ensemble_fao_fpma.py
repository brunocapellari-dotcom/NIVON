"""Contratos sintéticos Open-Meteo GloFAS/Ensemble e FAO FPMA."""
import json
import unittest
from datetime import datetime, timezone

from nivon.open_meteo_hidro_ensemble import (
 ErroAgroClimaAberto, normalizar_vazao, normalizar_ensemble,
 consultar_vazao, consultar_ensemble, planejar_vazao, planejar_ensemble)
from nivon.fao_fpma_publica import (
 ErroFAOFPMA, normalizar_catalogo, normalizar_precos,
 consultar_catalogo, consultar_precos, planejar_catalogo, planejar_precos)

NOW=datetime(2026,10,21,18,tzinfo=timezone.utc)
UID="10cc6802-cf70-4114-8cdf-45be23d6b2ee"


def flood():
    return {"latitude":-13.05,"longitude":-56.05,"utc_offset_seconds":0,
            "daily_units":{"river_discharge":"m³/s"},
            "daily":{"time":["2026-10-21","2026-10-22"],
                     "river_discharge":[153.0,None]}}


def ensemble():
    return {"latitude":-13.0,"longitude":-56.0,"utc_offset_seconds":0,
            "hourly_units":{"precipitation":"mm","precipitation_member01":"mm","precipitation_member02":"mm"},
            "hourly":{"time":["2026-10-21T00:00","2026-10-21T01:00"],
                      "precipitation":[0.2,0.3],
                      "precipitation_member01":[0.0,0.4],
                      "precipitation_member02":[1.2,None]}}


def catalog():
    return {"count":1,"next":None,"previous":None,
            "results":[{"uuid":UID,"iso3_country_code":"BRA",
                        "commodity":"Maize","price_type":"WHOLESALE",
                        "currency":"BRL","measure_unit_label":"100 kg"}]}


def prices():
    return {"count":1,"next":None,"previous":None,
            "results":[{"uuid":UID,"datapoints":[{
                "date":"2026-09-01","periodicity":"monthly",
                "price_value":123.5,"price_value_real":None,"price_value_dollar":27.8,
                "conversion_factor":0.01}]}]}


class Reply:
    status=200
    headers={"Content-Type":"application/json"}
    def __init__(self,url,body): self.url,self.body=url,body
    def __enter__(self): return self
    def __exit__(self,*args):return False
    def geturl(self):return self.url
    def read(self,n):return self.body[:n]


class Client:
    def __init__(self,obj):self.obj=obj;self.calls=[]
    def open(self,req,timeout):
        self.calls.append(req.full_url)
        return Reply(req.full_url,json.dumps(self.obj).encode())


class TestAgroAPIs(unittest.TestCase):
    def test_flood_vazao_modelada_com_nulo(self):
        a=Client(flood())
        with self.assertRaises(PermissionError):
            consultar_vazao(latitude=-13,longitude=-56,abridor=a)
        self.assertEqual(len(a.calls),0)
        d=consultar_vazao(latitude=-13,longitude=-56,dias=2,executar=True,abridor=a,instante=NOW)["dados"]
        self.assertEqual(d["quantidade"],2)
        self.assertEqual(d["observacoes"][0]["vazao_simulada_m3_s"],153.0)
        self.assertIsNone(d["observacoes"][1]["vazao_simulada_m3_s"])
        self.assertFalse(d["navegabilidade_inferivel"])
        self.assertFalse(d["vinculo_estacao_ANA_validado"])
        self.assertEqual(len(a.calls),1)
        with self.assertRaises(ErroAgroClimaAberto):
            planejar_vazao(latitude=-13,longitude=-56,dias=400)

    def test_flood_unidades_erradas_bloqueadas(self):
        b=flood();b["daily_units"]["river_discharge"]="mm"
        with self.assertRaises(ErroAgroClimaAberto):
            normalizar_vazao(json.dumps(b).encode(),latitude=-13,longitude=-56,dias=2,coletado_em="2026-10-21T18:00:00Z")

    def test_ensemble_preserva_membros_e_nao_calibra_risco(self):
        a=Client(ensemble())
        d=consultar_ensemble(latitude=-13,longitude=-56,dias=1,executar=True,abridor=a,instante=NOW)["dados"]
        self.assertEqual(d["numero_membros"],2)
        self.assertEqual(d["numero_horas"],2)
        self.assertEqual(d["membros"]["precipitation_member02"],[1.2,None])
        self.assertFalse(d["apto_probabilidade_calibrada"])
        self.assertFalse(d["apto_publicacao_automatica"])
        self.assertEqual(len(a.calls),1)
        with self.assertRaises(ErroAgroClimaAberto):
            planejar_ensemble(latitude=-13,longitude=-56,modelo="evil")

    def test_fpma_catalogo_sem_precos_inventados(self):
        a=Client(catalog())
        with self.assertRaises(PermissionError):
            consultar_catalogo(abridor=a)
        d=consultar_catalogo(executar=True,abridor=a,instante=NOW)["dados"]
        self.assertEqual(d["series"][0]["uuid"],UID)
        self.assertEqual(d["series"][0]["moeda_metadado"],"BRL")
        self.assertTrue(d["paginacao_completa"])
        self.assertEqual(len(a.calls),1)

    def test_fpma_price_original_nao_spot_brasileiro(self):
        a=Client(prices())
        d=consultar_precos(serie_uuid=UID,executar=True,abridor=a,instante=NOW)["dados"]
        self.assertEqual(d["observacoes"][0]["valor_original"],"123.5")
        self.assertIsNone(d["observacoes"][0]["moeda_e_unidade"])
        self.assertTrue(d["dados_sem_metadados_unidade"])
        self.assertFalse(d["apto_publicacao_automatica"])
        with self.assertRaises(ErroFAOFPMA):
            planejar_precos(serie_uuid="__bad_uuid__")

    def test_catalogo_paginas_nao_seguidas_e_fechamento(self):
        s=catalog();s["next"]="https://bad.invalid/capture"
        d=normalizar_catalogo(json.dumps(s).encode(),pais="BRA",pagina=1,coletado_em="2026-10-21T18:00:00Z")
        self.assertFalse(d["paginacao_completa"])
        self.assertNotIn("bad.invalid",str(d))
        p=prices();p["results"][0]["datapoints"][0]["price_value"]=-1
        with self.assertRaises(ErroFAOFPMA):
            normalizar_precos(json.dumps(p).encode(),serie_uuid=UID,periodicidade="monthly",coletado_em="2026-10-21T18:00:00Z")


if __name__=="__main__":
    unittest.main()
