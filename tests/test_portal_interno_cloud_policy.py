"""Gates de deploy do snapshot: jamais liberar cron por mera existencia de API."""
import unittest
from datetime import datetime,timezone
from scripts.atualizar_snapshot_portal_gcp import planejar, ARQUIVO_PRIVADO
from nivon.portal_interno import ErroPortal


class PortalCloudPolicy(unittest.TestCase):
    def test_gcp_contrato_e_teto(self):
        d=planejar(projeto="nivon-data",dataset="nivon_raw",bucket="nivon-data-raw-2026",
            competencia="2026-08",agora=datetime(2026,10,25,tzinfo=timezone.utc))
        self.assertEqual(d["objeto_privado"],ARQUIVO_PRIVADO)
        self.assertEqual(len(d["consulta"]["consultas_maritimas_bigquery"]),2)
        self.assertEqual(d["consulta"]["ferrovia_bigquery"]["competencia"],"2026-08")
        self.assertEqual(d["consulta"]["consultas_maritimas_bigquery"][0]["inicio"],"2026-10-01")
        for kwargs in ({"competencia":"2026-11"},{"dataset":"other"},{"bucket":"public"},
                       {"competencia":"2026-00"}):
            base=dict(projeto="nivon-data",dataset="nivon_raw",
                      bucket="nivon-data-raw-2026",competencia="2026-08",
                      agora=datetime(2026,10,25,tzinfo=timezone.utc))
            with self.subTest(k=kwargs),self.assertRaises(ErroPortal):
                planejar(**(base|kwargs))

    def test_pipeline_real_pode_ser_testado_sem_nuvem(self):
        from scripts.atualizar_snapshot_portal_gcp import executar
        from hashlib import sha256
        class Blob:
            generation = 0
            data = None
            metadata = None
            cache_control = None
            uploaded = {}
            def reload(self):
                if self.data is None:
                    raise FileNotFoundError()
            def upload_from_string(self, raw, **kwargs):
                assert kwargs["if_generation_match"] == self.generation
                assert kwargs["checksum"] == "crc32c"
                self.uploaded=kwargs
                self.data=raw
                self.generation+=1
            def download_as_bytes(self):
                return self.data
        class Bucket:
            location="southamerica-east1"
            def __init__(self):
                self.obj=Blob()
            def blob(self,name):
                assert name==ARQUIVO_PRIVADO
                return self.obj
        b=Bucket()
        class Client:
            def __init__(self,project):
                assert project=="nivon-data"
            def get_bucket(self,name):
                assert name=="nivon-data-raw-2026"
                return b
        def fake_readback(config,*,as_of,executar_bigquery):
            self.assertTrue(executar_bigquery)
            self.assertEqual(config["ferrovia_bigquery"]["competencia"],"2026-08")
            return {"status":"ANALISE_SHADOW_NAO_HOMOLOGADA",
                    "executou_bigquery":True,
                    "ferrovia":{
                        "executado":True, "publicavel":False,
                        "as_of":as_of,"estado":"REVISAO_ATUAL_CONSULTADA_NAO_HOMOLOGADA",
                        "fonte":"ANTT_SIADE_ORIGEM_DESTINO",
                        "competencia":"2026-08",
                        "historico_pit_reconstruido":False,
                        "transbordo_confirmado":False,
                        "linhas_view":1,"arquivos_sha256":["a"*64],
                        "polos_ferroviarios":[{"polo":{"id":"MT_RONDONOPOLIS_FERRO"},
                                              "toneladas_ferroviarias":"1800"}],
                    },
                    "fontes_maritimas_bigquery":[]}
        kw=dict(projeto="nivon-data",dataset="nivon_raw",
            bucket="nivon-data-raw-2026",competencia="2026-08",
            agora=datetime(2026,10,25,tzinfo=timezone.utc),
            analisar=fake_readback,storage_factory=Client)
        result=executar(**kw)
        self.assertEqual(result["status"],"SNAPSHOT_PRIVADO_GCS_VERIFICADO")
        self.assertTrue(result["readback_sha256_ok"])
        self.assertFalse(result["publicavel"])
        doc=__import__("json").loads(b.obj.data)
        self.assertFalse(doc["go_live_publico"])
        self.assertEqual(doc["indicadores"][0]["valor"],"1800")
        self.assertEqual(b.obj.metadata["sha256"],sha256(b.obj.data).hexdigest())
        self.assertEqual(b.obj.cache_control,"private, no-store")
        self.assertEqual(b.obj.uploaded["if_generation_match"],0)
        result=executar(**kw)
        self.assertEqual(result["status"],"SNAPSHOT_PRIVADO_GCS_VERIFICADO")
        self.assertEqual(b.obj.uploaded["if_generation_match"],1)
        def fake_bad(config,*,as_of,executar_bigquery):
            return {"status":"ANALISE_SHADOW_NAO_HOMOLOGADA",
                    "executou_bigquery":False}
        with self.assertRaises(ErroPortal):
            executar(**(kw|{"analisar":fake_bad}))
        self.assertEqual(b.obj.generation,2)



if __name__=="__main__":
    unittest.main()
