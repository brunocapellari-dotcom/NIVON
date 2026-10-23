"""Contrato do CEMADEN PED testado com fixture sintética, sem token real."""
import io
import json
import os
import unittest
from unittest.mock import patch
from urllib.error import HTTPError

from nivon.cemaden_ped import (
    ErroCemaden, construir_requisicao, normalizar_acumulados, consultar_acumulados
)


class Resposta:
    status=200
    def __init__(self, data):self.buffer=io.BytesIO(data)
    def __enter__(self):return self
    def __exit__(self,*args):return False
    def read(self,n):return self.buffer.read(n)


class Transporte:
    def __init__(self, data, error=None):
        self.data,self.error,self.calls,self.req=data,error,0,None
    def open(self,req,timeout):
        self.calls+=1
        self.req=req
        if self.error:
            raise HTTPError(req.full_url,self.error,"token=PRIVADO",{},None)
        return Resposta(self.data)


FIXTURE=json.dumps([{"acc1hr":2.3,"acc3hr":5.1,"acc24hr":7.2,
                     "codestacao":"292740804A","codibge":2927408,
                     "datahora":"2026-10-21T13:50:00"}]).encode()


class TestCemadenPED(unittest.TestCase):
    def test_endpoint_restrito_e_jwt_exclusivo_header(self):
        req=construir_requisicao(codigo_ibge="2927408",token="T"*60)
        self.assertEqual(req.full_url.split("?")[0],
                         "https://sws.cemaden.gov.br/PED/rest/pcds-acum/acumulados-recentes")
        self.assertIn("codibge=2927408",req.full_url)
        self.assertNotIn("T"*60,req.full_url)
        self.assertEqual(req.get_header("Token"),"T"*60)

    def test_data_bruta_nao_promove_automaticamente(self):
        doc=normalizar_acumulados(FIXTURE,codigo_ibge="2927408")
        self.assertEqual(len(doc["registros"]),1)
        row=doc["registros"][0]
        self.assertEqual(row["acumulados_mm"]["acc24hr"],7.2)
        self.assertEqual(row["natureza"],"OBSERVADO_BRUTO_SEM_QC")
        self.assertFalse(row["utilizar_para_modelo"])
        self.assertFalse(row["fuso_validado_independentemente"])
        self.assertFalse(doc["homologado"])

    def test_rede_e_token_requerem_optin(self):
        t=Transporte(FIXTURE)
        with self.assertRaises(PermissionError):
            consultar_acumulados(codigo_ibge="2927408",transporte=t)
        self.assertEqual(t.calls,0)
        with patch.dict(os.environ,{"NIVON_CEMADEN_TOKEN":""}):
            with self.assertRaises(ErroCemaden):
                consultar_acumulados(codigo_ibge="2927408",habilitar_rede=True,transporte=t)
        self.assertEqual(t.calls,0)
        with patch.dict(os.environ,{"NIVON_CEMADEN_TOKEN":"S"*60}):
            x=consultar_acumulados(codigo_ibge="2927408",habilitar_rede=True,transporte=t)
        self.assertEqual(t.calls,1)
        self.assertIsNotNone(x["data_coleta"])
        self.assertNotIn("S"*60,json.dumps(x))

    def test_rejeita_outro_municipio_malformacao_duplicata_ou_chuva_negativa(self):
        src=json.loads(FIXTURE)
        for item in (
            {"error":"sem autorizacao"},
            [{**src[0],"codibge":2927409}],
            [{**src[0],"acc1hr":-2}],
            [src[0],src[0]],
            [{**src[0],"datahora":"timestamp invalido"}],
        ):
            with self.subTest(item=item),self.assertRaises(ErroCemaden):
                normalizar_acumulados(json.dumps(item).encode(),codigo_ibge="2927408")

    def test_erro_http_nao_vaza_exception_do_servidor(self):
        t=Transporte(b"",error=401)
        with patch.dict(os.environ,{"NIVON_CEMADEN_TOKEN":"S"*60}):
            with self.assertRaises(ErroCemaden) as ctx:
                consultar_acumulados(codigo_ibge="2927408",
                                    habilitar_rede=True,transporte=t)
        self.assertNotIn("PRIVADO",str(ctx.exception))
        self.assertNotIn("S"*60,str(ctx.exception))


if __name__=="__main__":
    unittest.main()
