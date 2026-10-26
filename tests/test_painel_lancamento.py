"""Contrato da primeira entrega real NIVON, inteiramente offline."""
from __future__ import annotations
from datetime import datetime,timezone
from decimal import Decimal
from pathlib import Path
import importlib.util
import json
import subprocess
import sys
import unittest

from nivon.painel_lancamento import construir_retrato, renderizar_html, ErroLancamento

SCRIPT=Path(__file__).resolve().parents[1]/"scripts"/"publicar_painel_interno.py"
spec=importlib.util.spec_from_file_location("publicar_painel_interno",str(SCRIPT))
mod=importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)
AS_OF="2026-10-25T20:00:00Z"


def mock_painel():
    return {
        "status":"ANALISE_SHADOW_NAO_HOMOLOGADA",
        "executou_bigquery":True,
        "ferrovia":{
            "estado":"REVISAO_ATUAL_CONSULTADA_NAO_HOMOLOGADA",
            "executado":True,"competencia":"2026-08",
            "fonte":"ANTT_SIADE_ORIGEM_DESTINO",
            "historico_pit_reconstruido":False,"transbordo_confirmado":False,
            "publicavel":False,"arquivos_sha256":["a"*64],
            "linhas_view":3,
            "polos_ferroviarios":[
                {"polo":{"id":"MT_RONDONOPOLIS_FERRO"},
                 "toneladas_ferroviarias":"120000.5","terminal_comprovado":False},
                {"polo":{"id":"MT_ITIQUIRA_FERRO"},
                 "toneladas_ferroviarias":"10000.5","terminal_comprovado":False},
            ]
        },
        "fontes_maritimas_bigquery":[
            {
                "executado":True,"publicavel":False,"fonte":"imbituba",
                "passagem":None,
                "estado":"PROGRAMACAO_HISTORICA_READONLY_SHADOW",
                "vinculo_duv_confirmado":False,
                "navios_operados_confirmados":None,"toneladas_realizadas":None,
                "ids_programacao_distintos":5,"revisoes_visiveis":7,
            },
            {
                "executado":True,"publicavel":False,"fonte":None,
                "passagem":"panama",
                "estado":"PORTWATCH_TRANSITOS_ESTIMADOS_SHADOW",
                "volume_movimentado_real":None,"revisoes_visiveis":4,
                "dias_distintos":3,"volume_estimado_modelo_t":"23000.5",
            }
        ]
    }


class FakeBlob:
    def __init__(self,bucket,name):
        self.bucket=bucket;self.name=name;self.metadata={};self.generation=None
    def upload_from_string(self,data,*,content_type,if_generation_match):
        existing=self.bucket.objects.get(self.name)
        prior=existing["generation"] if existing else 0
        if prior!=if_generation_match:
            raise AssertionError("precondition GCS alterada")
        self.bucket.objects[self.name]={"value":data,"generation":prior+1,
                                       "metadata":self.metadata,"mime":content_type}
        self.generation=prior+1
    def exists(self):
        v=self.bucket.objects.get(self.name)
        if v:self.generation=v["generation"]
        return bool(v)
    def download_as_bytes(self):
        return self.bucket.objects[self.name]["value"]


class FakeBucket:
    def __init__(self,public_access_prevention="enforced"):
        self.iam_configuration=type("Iam",(),{"public_access_prevention":public_access_prevention})()
        self.objects={}
    def blob(self,name):return FakeBlob(self,name)
    def reload(self):pass
    def get_iam_policy(self,requested_policy_version):return {"bindings":[]}


class FakeStorage:
    def __init__(self,bucket):self.target=bucket
    def bucket(self,name):return self.target


class TestPrimeiroGoLive(unittest.TestCase):
    def test_renderiza_relatorio_com_corte_e_unidades(self):
        p=construir_retrato(mock_painel(),as_of=AS_OF)
        self.assertEqual(p["status"],"ATIVO_INTERNO_SHADOW")
        self.assertEqual(p["ferrovia"]["toneladas_recorte_polos"],"130001.0")
        self.assertEqual(p["imbituba"]["ids_programacao"],5)
        self.assertIsNone(p["imbituba"]["toneladas_realizadas"])
        self.assertFalse(p["ferrovia"]["somar_com_rodovia"])
        h=renderizar_html(p)
        for val in ("130.001 t","IMBITUBA","PortWatch","SHADOW","noindex,nofollow"):
            self.assertIn(val,h)
        self.assertNotIn("https://cdn",h)

    def test_data_e_tonelagem_nao_podem_ser_futuro_sem_fuso_nan(self):
        v=mock_painel()
        v["ferrovia"]["polos_ferroviarios"][0]["toneladas_ferroviarias"]="NaN"
        with self.assertRaises(ErroLancamento):
            construir_retrato(v,as_of=AS_OF)
        with self.assertRaises(ErroLancamento):
            construir_retrato(mock_painel(),as_of="2026-10-25T20:00:00")

    def test_xss_de_nome_polo_e_escapado(self):
        v=mock_painel()
        v["ferrovia"]["polos_ferroviarios"][0]["polo"]["id"]="MT_<script>alert(1)</script>"
        h=renderizar_html(construir_retrato(v,as_of=AS_OF))
        self.assertNotIn("<script>",h)
        self.assertIn("&lt;script&gt;",h)

    def test_nega_publicacao_se_coleta_nao_executou(self):
        v=mock_painel();v["executou_bigquery"]=False
        with self.assertRaises(ErroLancamento):
            construir_retrato(v,as_of=AS_OF)

    def test_recusa_inferir_operacoes_reais(self):
        for field,value in (("toneladas_realizadas","100"),
                            ("navios_operados_confirmados",5),
                            ("vinculo_duv_confirmado",True)):
            v=mock_painel();v["fontes_maritimas_bigquery"][0][field]=value
            with self.subTest(field=field),self.assertRaises(ErroLancamento):
                construir_retrato(v,as_of=AS_OF)

    def test_bloqueia_fonte_ou_rev_portwatch_erradas(self):
        v=mock_painel()
        v["fontes_maritimas_bigquery"][1]["volume_movimentado_real"]="100"
        with self.assertRaises(ErroLancamento):
            construir_retrato(v,as_of=AS_OF)
        v=mock_painel()
        v["fontes_maritimas_bigquery"][1]["passagem"]="suez"
        with self.assertRaises(ErroLancamento):
            construir_retrato(v,as_of=AS_OF)

    def test_recusa_vintage_ferrovia_e_polo_como_terminal(self):
        for key,value in (("historico_pit_reconstruido",True),
                          ("transbordo_confirmado",True),
                          ("competencia","2025-08")):
            v=mock_painel();v["ferrovia"][key]=value
            with self.subTest(key=key),self.assertRaises(ErroLancamento):
                construir_retrato(v,as_of=AS_OF)
        v=mock_painel()
        v["ferrovia"]["polos_ferroviarios"][0]["terminal_comprovado"]=True
        with self.assertRaises(ErroLancamento):
            construir_retrato(v,as_of=AS_OF)

    def test_produz_produto_com_leitor_injetado(self):
        calls=[]
        def reader(config,*,as_of,executar_bigquery):
            calls.append((config,as_of,executar_bigquery))
            return mock_painel()
        doc,html,payload=mod.criar_produto(AS_OF,leitor=reader)
        self.assertTrue(calls[0][2])
        self.assertEqual(calls[0][0]["ferrovia_bigquery"]["competencia"],"2026-08")
        self.assertEqual(len(calls[0][0]["consultas_maritimas_bigquery"]),2)
        self.assertIn(b"NIVON",html)
        self.assertEqual(json.loads(payload)["privacidade"],"INTERNO_PRIVADO")

    def test_faz_upload_privado_idempotencia_limited(self):
        doc,html,payload=mod.criar_produto(AS_OF,leitor=lambda *a,**kw:mock_painel())
        bucket=FakeBucket()
        summary=mod.publicar_no_gcs(bucket=mod.BUCKET,html=html,payload=payload,
                    corte=AS_OF,storage_client=FakeStorage(bucket))
        self.assertEqual(summary["status"],"PUBLICADO_SOMENTE_GCS_PRIVADO")
        self.assertEqual(summary["objetos"],4)
        self.assertEqual(len(bucket.objects),4)
        self.assertTrue(all(x.startswith("nivon/painel-interno/") for x in bucket.objects))
        self.assertTrue(all(v["metadata"]["nivon-classe"]=="INTERNO_PRIVADO"
                            for v in bucket.objects.values()))
        with self.assertRaises(AssertionError):
            mod.publicar_no_gcs(bucket=mod.BUCKET,html=html,payload=payload,
                    corte=AS_OF,storage_client=FakeStorage(bucket))

    def test_nega_bucket_sem_prova_iam_privado(self):
        doc,html,payload=mod.criar_produto(AS_OF,leitor=lambda *a,**kw:mock_painel())
        with self.assertRaises(ErroLancamento):
            mod.publicar_no_gcs(bucket=mod.BUCKET,html=html,payload=payload,
                corte=AS_OF,storage_client=FakeStorage(FakeBucket("inherited")))
        with self.assertRaises(ErroLancamento):
            mod.publicar_no_gcs(bucket="outro-bucket",html=html,payload=payload,
                corte=AS_OF,storage_client=FakeStorage(FakeBucket()))

    def test_status_lacuna_portwatch_nao_e_zero(self):
        v=mock_painel()
        port=v["fontes_maritimas_bigquery"][1]
        port["estado"]="SEM_DADOS_NAO_EQUIVALE_A_ZERO"
        port["revisoes_visiveis"]=0
        port["volume_estimado_modelo_t"]=None
        doc=construir_retrato(v,as_of=AS_OF)
        self.assertEqual(doc["status"],"ATIVO_COM_LACUNA_PORTWATCH")
        self.assertIsNone(doc["portwatch"]["volume_estimado_modelo_t"])

    def test_dry_run_cli_nao_tem_credenciais(self):
        run=subprocess.run([sys.executable,str(SCRIPT),"--as-of",AS_OF],
                           capture_output=True,text=True,timeout=20)
        self.assertEqual(run.returncode,0,run.stderr)
        doc=json.loads(run.stdout)
        self.assertEqual(doc["status"],"PLANO_SEM_REDE")
        self.assertEqual(doc["consultas"]["ferrovia_bigquery"]["projeto"],"nivon-data")
        self.assertEqual(len(doc["consultas"]["consultas_maritimas_bigquery"]),2)


if __name__=="__main__":
    unittest.main()
