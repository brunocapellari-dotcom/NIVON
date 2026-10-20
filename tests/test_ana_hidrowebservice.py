import hashlib
import io
import json
import os
import unittest
from unittest.mock import patch

from nivon.ana_hidrowebservice import (
    BASE, LOGIN, ErroANAAPI, SessaoANA,
    credenciais_ambiente, construir_login, construir_consulta_adotada,
    efetuar_request, extrair_token, normalizar_adotada,
)

def pack(items):
    return json.dumps({"status":"OK","code":200,"message":"Sucesso",
                       "items":items}).encode()

def amostra(*,estado="0",valor="781.00",codigo="15400000",dia="2024-01-01 23:00:00.0"):
    return {"codigoestacao":codigo,"Data_Hora_Medicao":dia,
            "Chuva_Adotada":"0.00","Chuva_Adotada_Status":"0",
            "Cota_Adotada":valor,"Cota_Adotada_Status":estado,
            "Vazao_Adotada":"13225.42","Vazao_Adotada_Status":"0"}

class TestAutenticacaoSegura(unittest.TestCase):
    def test_credencial_somente_do_ambiente(self):
        with patch.dict(os.environ,{"NIVON_ANA_IDENTIFICADOR":"","NIVON_ANA_SENHA":""}):
            with self.assertRaises(ErroANAAPI):credenciais_ambiente()
        with patch.dict(os.environ,{"NIVON_ANA_IDENTIFICADOR":"12345678901",
                    "NIVON_ANA_SENHA":"senha_de_teste"}):
            self.assertEqual(credenciais_ambiente(),("12345678901","senha_de_teste"))

    def test_login_sem_senha_na_url(self):
        req=construir_login(identificador="12345678901",senha="senha_teste")
        self.assertEqual(req.full_url,LOGIN)
        self.assertEqual(req.get_method(),"GET")
        self.assertNotIn("senha_teste",req.full_url)
        self.assertEqual(req.get_header("Senha"),"senha_teste")
        with self.assertRaises(ErroANAAPI):
            construir_login(identificador="12345678901",senha="abc\nx")

    def test_token_validade_curta_sem_refresh_continuo(self):
        x=SessaoANA(token="a"*50,emitido_monotonic=100)
        self.assertEqual(x._ativo(200),"a"*50)
        with self.assertRaises(ErroANAAPI):x._ativo(3400)
        with self.assertRaises(ErroANAAPI):x._ativo(99)

    def test_token_somente_em_json_bem_formado(self):
        tok="a"*70
        self.assertEqual(extrair_token(pack({"tokenautenticacao":tok})),tok)
        with self.assertRaises(ErroANAAPI):
            extrair_token(pack({"tokenautenticacao":"abc"}))
        with self.assertRaises(ErroANAAPI):
            extrair_token(b'{"status":"OK","code":200,"items":{},"items":{}}')

    def test_rota_adotada_bearer_sem_credenciais_na_query(self):
        request=construir_consulta_adotada(estacao="15400000",token="x"*60,
                data_busca="2024-01-01")
        self.assertEqual(request.full_url.split("?")[0],
            BASE+"/HidroinfoanaSerieTelemetricaAdotada/v1")
        self.assertIn("CodigoDaEstacao=15400000",request.full_url)
        self.assertEqual(request.get_header("Authorization"),"Bearer "+"x"*60)
        with self.assertRaises(ErroANAAPI):
            construir_consulta_adotada(estacao="15400000",token="x"*60,
                data_busca="2024-01-01",intervalo="DIAS_400")

    def test_rede_negada_por_padrao(self):
        req=construir_login(identificador="12345678901",senha="test")
        with self.assertRaises(PermissionError):efetuar_request(req)

    def test_transporte_injetado_sem_rede_real(self):
        class FakeResponse:
            status=200
            def __enter__(self):return self
            def __exit__(self,*a):pass
            def read(self,n):return pack({"tokenautenticacao":"t"*70})
        class FakeOpener:
            def open(self,req,timeout):
                self.req=req;self.timeout=timeout
                return FakeResponse()
        req=construir_login(identificador="12345678901",senha="test")
        self.assertIn("tokenautenticacao",efetuar_request(req,
            habilitar_rede=True,transporte=FakeOpener()).decode())
        class WrongOpener:
            def open(self,req,timeout):raise RuntimeError("Senha:abc")
        with self.assertRaisesRegex(ErroANAAPI,"falha de acesso à API ANA"):
            efetuar_request(req,habilitar_rede=True,transporte=WrongOpener())

class TestTelemetriaANA(unittest.TestCase):
    def call(self,entries):
        data=pack(entries)
        return normalizar_adotada(data,estacao="15400000",
               zona_estacao="America/Manaus",coletado_em="2024-01-03T00:00:00Z",
               origem_sha256=hashlib.sha256(data).hexdigest())

    def test_documentacao_oficial_3_medidas(self):
        rows=self.call([amostra()])
        self.assertEqual(len(rows),3)
        by={x["variavel"]:x for x in rows}
        self.assertEqual(by["COTA_CM"]["valor"],781)
        self.assertEqual(by["VAZAO_M3_S"]["valor"],13225.42)
        self.assertEqual(by["CHUVA_INTERVALO_MM"]["valor"],0)
        self.assertTrue(all(x["utilizar_para_modelo"] for x in rows))
        self.assertEqual(by["COTA_CM"]["data_hora_medicao_utc"],
                         "2024-01-02T03:00:00+00:00")
        self.assertEqual(by["COTA_CM"]["publicacao"],None)

    def test_qc_suspeito_bloqueia_modelo(self):
        rows=self.call([amostra(estado="1")])
        cotas=[x for x in rows if x["variavel"]=="COTA_CM"]
        self.assertEqual(cotas[0]["qualidade"],"SUSPEITO")
        self.assertFalse(cotas[0]["utilizar_para_modelo"])

    def test_qc_ruim_bloqueia_modelo(self):
        rows=self.call([amostra(estado="2")])
        self.assertFalse(next(x for x in rows if x["variavel"]=="COTA_CM")["utilizar_para_modelo"])

    def test_registros_repetidos_bloqueados(self):
        with self.assertRaises(ErroANAAPI):
            self.call([amostra(),amostra()])

    def test_estacao_incorreta_bloqueia(self):
        with self.assertRaises(ErroANAAPI):
            self.call([amostra(codigo="00000000")])

    def test_valores_fisicos_incorretos_bloqueados(self):
        with self.assertRaises(ErroANAAPI):
            self.call([amostra(valor="NaN")])
        obj=amostra();obj["Vazao_Adotada"]="-1"
        with self.assertRaises(ErroANAAPI):self.call([obj])

    def test_fuso_da_estacao_deve_ser_explicito(self):
        payload=pack([amostra()])
        with self.assertRaises(ErroANAAPI):
            normalizar_adotada(payload,estacao="15400000",
                    zona_estacao="UTC+3",coletado_em="2024-01-03T00:00:00Z",
                    origem_sha256=hashlib.sha256(payload).hexdigest())

if __name__=="__main__":unittest.main()
