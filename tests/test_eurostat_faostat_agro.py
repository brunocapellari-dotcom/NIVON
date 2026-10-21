"""Testar decodificação JSON-stat Eurostat e FAOSTAT em HTTP simulado."""
import json
import unittest
from datetime import datetime,timezone
from nivon.eurostat_faostat_agro import (
 ErroEstatisticasAgro, normalizar_eurostat, normalizar_faostat,
 consultar_eurostat, consultar_faostat, planejar_eurostat, planejar_faostat)

NOW=datetime(2026,10,21,20,tzinfo=timezone.utc)


def jsonstat():
    return {"version":"2.0","class":"dataset","label":"Area oilseeds",
      "id":["freq","crops","strucpro","geo","time"],"size":[1,3,1,1,1],
      "dimension":{
        "freq":{"category":{"index":{"A":0}}},
        "crops":{"category":{"index":{"I1110":0,"I1120":1,"I1130":2}}},
        "strucpro":{"category":{"index":{"AR_THS_HA":0}}},
        "geo":{"category":{"index":{"FR":0}}},
        "time":{"category":{"index":{"2024":0}}}},
      "value":{"0":100.2,"1":80.1,"2":0.5},
      "status":{"0":"e","2":"p"},"updated":"2026-10-20T11:00:00+02:00"}


def fao():
    return {"data":[
       ["Area Code","Item Code","Element Code","Year","Unit","Value","Flag"],
       [21,236,5510,2023,"t",154000000,"A"]]}


class Response:
    status=200
    headers={"Content-Type":"application/json"}
    def __init__(self,url,b):self.url,self.blob=url,b
    def __enter__(self):return self
    def __exit__(self,*a):return False
    def geturl(self):return self.url
    def read(self,n):return self.blob[:n]


class Opener:
    def __init__(self,obj):self.obj=obj;self.urls=[]
    def open(self,req,timeout):
        self.urls.append(req.full_url)
        return Response(req.full_url,json.dumps(self.obj).encode())


class TestAgroEstatisticas(unittest.TestCase):
    def test_eurostat_flatten_flags_units_provenance(self):
        op=Opener(jsonstat())
        with self.assertRaises(PermissionError):
            consultar_eurostat(abridor=op)
        self.assertEqual(op.urls,[])
        d=consultar_eurostat(pais="FR",ano=2024,executar=True,abridor=op,instante=NOW)
        self.assertEqual(len(op.urls),1)
        self.assertEqual(d["numero_observacoes"],3)
        self.assertEqual(d["observacoes"][0]["valor_mil_ha"],"100.2")
        self.assertEqual(d["observacoes"][0]["flag_fonte"],"e")
        self.assertEqual(d["observacoes"][2]["flag_fonte"],"p")
        self.assertIsNone(d["observacoes"][0]["publicacao"])
        self.assertEqual(d["observacoes"][0]["unidade"],"MIL_HECTARES")
        self.assertEqual(d["updated_dataset_fonte"],"2026-10-20T11:00:00+02:00")

    def test_faostat_obj_and_rows_no_fake_safra(self):
        op=Opener(fao())
        d=consultar_faostat(pais="BRA",cultura="SOJA",ano=2023,executar=True,abridor=op,instante=NOW)
        self.assertEqual(d["numero_observacoes"],1)
        self.assertEqual(d["observacoes"][0]["valor_original"],"154000000")
        self.assertEqual(d["observacoes"][0]["unidade_original"],"t")
        self.assertIn("NAO_ESTIMATIVA",d["observacoes"][0]["natureza"])
        self.assertEqual(len(op.urls),1)
        obj={"data":[dict(zip(fao()["data"][0],fao()["data"][1]))]}
        d2=normalizar_faostat(json.dumps(obj).encode(),pais="BRA",cultura="SOJA",ano=2023,coletado_em="2026-10-21T20:00:00Z")
        self.assertEqual(d2["numero_observacoes"],1)

    def test_rejeitar_injecao_ano_pais_item(self):
        for kw in ({"pais":"evil"},{"ano":"2024;DROP"}):
            with self.assertRaises(ErroEstatisticasAgro):
                planejar_eurostat(**kw)
        for kw in ({"pais":"ARG OR 1=1"},{"cultura":"CAFÉ"},{"ano":1500}):
            with self.assertRaises(ErroEstatisticasAgro):
                planejar_faostat(**kw)

    def test_eurostat_estrutra_tem_que_conferir(self):
        a=jsonstat()
        a["dimension"]["strucpro"]["category"]["index"]={"PRD_THS_T":0}
        with self.assertRaises(ErroEstatisticasAgro):
            normalizar_eurostat(json.dumps(a).encode(),pais="FR",ano=2024,coletado_em="2026-10-21T20:00:00Z")
        b=jsonstat();b["dimension"]["geo"]["category"]["index"]={"DE":0}
        with self.assertRaises(ErroEstatisticasAgro):
            normalizar_eurostat(json.dumps(b).encode(),pais="FR",ano=2024,coletado_em="2026-10-21T20:00:00Z")

    def test_faostat_recusa_ano_ou_area_diferentes(self):
        b=fao()
        b["data"][1][0]=231
        with self.assertRaises(ErroEstatisticasAgro):
            normalizar_faostat(json.dumps(b).encode(),pais="BRA",cultura="SOJA",ano=2023,coletado_em="2026-10-21T20:00:00Z")
        b=fao();b["data"][1][5]="NaN"
        with self.assertRaises(ErroEstatisticasAgro):
            normalizar_faostat(json.dumps(b).encode(),pais="BRA",cultura="SOJA",ano=2023,coletado_em="2026-10-21T20:00:00Z")


if __name__=="__main__":
    unittest.main()
