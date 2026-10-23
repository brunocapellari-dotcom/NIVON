"""Testes de observações agrícolas oficiais: parser -> HTTP -> ledger -> export."""
import json
import tempfile
import unittest
from pathlib import Path
from datetime import datetime,timezone

from nivon.coletores_agro_ibge_wdi import (
    ESTADOS,INDICADORES,plano_ibge_pam,parse_ibge_pam,coletar_ibge_pam,
    plano_wdi,parse_wdi,coletar_wdi,ErroFonteAgro)
from nivon.ingestao_fontes_reais import exportar_jsonl

T=datetime(2026,10,23,tzinfo=timezone.utc)
IBGE=[
 {"id":"214","variavel":"Quantidade produzida","unidade":"Toneladas",
  "resultados":[
   {"classificacoes":[{"id":"81","categoria":{"2713":"Soja (em grão)"}}],
    "series":[{"localidade":{"id":"51","nome":"Mato Grosso"},
               "serie":{"2024":"42800000"}}]},
   {"classificacoes":[{"id":"81","categoria":{"2714":"Milho (em grão)"}}],
    "series":[{"localidade":{"id":"51","nome":"Mato Grosso"},
               "serie":{"2024":".." }}]}
  ]}
]
WDI=[{"page":1,"pages":1,"per_page":100,"total":2},
      [{"countryiso3code":"BRA","indicator":{"id":"AG.YLD.CREL.KG"},
        "date":"2024","value":5001.4,"obs_status":""},
       {"countryiso3code":"BRA","indicator":{"id":"AG.YLD.CREL.KG"},
        "date":"2023","value":4200.2,"obs_status":"F"}]]
class Resp:
    status=200
    headers={"Content-Type":"application/json; charset=utf-8"}
    def __init__(self,url,raw): self.url=url;self.raw=raw
    def geturl(self): return self.url
    def read(self,limite): return self.raw[:limite]
    def __enter__(self): return self
    def __exit__(self,*args):return False
class Fake:
    def __init__(self,url,raw):self.url=url;self.raw=raw;self.count=0
    def open(self,req,timeout=30):
        assert req.full_url==self.url,req.full_url
        self.count+=1
        return Resp(self.url,self.raw)

class FontesAgroTest(unittest.TestCase):
    def test_pam_producao_e_nao_interpolar_sigilosos(self):
        raw=json.dumps(IBGE).encode()
        obs=parse_ibge_pam(raw,ano=2024,uf="MT")
        self.assertEqual(len(obs),1)
        self.assertEqual(obs[0]["valor"],"42800000")
        self.assertEqual(obs[0]["unidade"],"t")
        self.assertEqual(obs[0]["campos"]["produto"],"SOJA")
        self.assertEqual(obs[0]["referencia"],"2024-12-31")
        bad=json.loads(raw)
        bad[0]["unidade"]="Quilogramas"
        with self.assertRaises(ErroFonteAgro):
            parse_ibge_pam(json.dumps(bad).encode(),ano=2024,uf="MT")
        bad=json.loads(raw)
        bad[0]["resultados"][0]["series"][0]["localidade"]["id"]="52"
        with self.assertRaises(ErroFonteAgro):
            parse_ibge_pam(json.dumps(bad).encode(),ano=2024,uf="MT")

    def test_wdi_estatistica_projetada_e_informada(self):
        rows=parse_wdi(json.dumps(WDI).encode(),pais="BRA",
                indicador="AG.YLD.CREL.KG",inicio=2023,fim=2024)
        self.assertEqual(len(rows),2)
        self.assertEqual({r["natureza"] for r in rows},{"PROJETADO","INFORMADO"})
        self.assertEqual({r["unidade"] for r in rows},{"kg/ha"})
        bad=json.loads(json.dumps(WDI))
        bad[0]["pages"]=2
        with self.assertRaises(ErroFonteAgro):
            parse_wdi(json.dumps(bad).encode(),pais="BRA",
                indicador="AG.YLD.CREL.KG",inicio=2023,fim=2024)
        bad=json.loads(json.dumps(WDI))
        bad[1][0]["countryiso3code"]="ARG"
        with self.assertRaises(ErroFonteAgro):
            parse_wdi(json.dumps(bad).encode(),pais="BRA",
                indicador="AG.YLD.CREL.KG",inicio=2023,fim=2024)

    def test_persistencia_e_idempotencia_ibge_e_wdi(self):
        with tempfile.TemporaryDirectory() as td:
            d=Path(td);db=d/"raw.sqlite";out=d/"out.jsonl"
            u=plano_ibge_pam(ano=2024,uf="MT")
            client=Fake(u,json.dumps(IBGE).encode())
            args=dict(ano=2024,uf="MT",banco=db,raw_dir=d/"raw",
                      executar=True,cliente=client,instante=T)
            a=coletar_ibge_pam(**args)
            b=coletar_ibge_pam(**args)
            self.assertEqual((a["novas_observacoes"],b["novas_observacoes"]),(1,0))
            w=plano_wdi(pais="BRA",indicador="AG.YLD.CREL.KG",inicio=2023,fim=2024)
            wfake=Fake(w,json.dumps(WDI).encode())
            z=coletar_wdi(pais="BRA",indicador="AG.YLD.CREL.KG",
                inicio=2023,fim=2024,banco=db,raw_dir=d/"raw",
                executar=True,cliente=wfake,instante=T)
            self.assertEqual(z["novas_observacoes"],2)
            result=exportar_jsonl(banco=db,destino=out)
            self.assertEqual(result["observacoes"],3)
            self.assertEqual({json.loads(v)["dataset_id"] for v in out.read_text().splitlines()},
                {"BR_IBGE_PAM_PRODUCAO_UF","WORLD_BANK_AGRO_INDICADORES"})
    def test_failclosed_nos_planos(self):
        for uf in ("BR", "XX", "MT/../../"):
            with self.assertRaises(ErroFonteAgro):
                plano_ibge_pam(ano=2024,uf=uf)
        for kw in (dict(pais="BR"),dict(indicador="MALFORMED"),
                   dict(inicio=1990,fim=2024)):
            with self.assertRaises(ErroFonteAgro):
                plano_wdi(**{**{"pais":"BRA","indicador":"AG.YLD.CREL.KG",
                                 "inicio":2023,"fim":2024},**kw})
        with self.assertRaises(PermissionError):
            coletar_ibge_pam(ano=2024,uf="MT",banco="/tmp/x",raw_dir="/tmp/raw")
        with self.assertRaises(PermissionError):
            coletar_wdi(pais="BRA",indicador="AG.YLD.CREL.KG",
                        inicio=2023,fim=2024,banco="/tmp/x",raw_dir="/tmp/raw")
if __name__=="__main__":
    unittest.main()
