"""SGS11 NIVON: coleta oficial e ponte unica GCS/BigQuery simulada."""
import json
import tempfile
import unittest
from datetime import datetime,timezone
from pathlib import Path
from nivon.conectores_publicos_gcp import coletar_selic_diaria
from nivon.bcb_sgs_selic import URL_PONTUAL
from scripts.coletar_sgs_google_cloud import executar_sgs

OPS=frozenset({"COLETA","ARMAZENAMENTO","PROCESSAMENTO"})
PAYLOAD=b'[{"data":"22/10/2026","valor":"0,055"}]'

class Resposta:
    status=200
    headers={"Content-Type":"application/json"}
    def geturl(self):return URL_PONTUAL
    def read(self,n):return PAYLOAD[:n]
    def __enter__(self):return self
    def __exit__(self,*args):return False

class Abridor:
    def open(self,req,timeout):return Resposta()

class Blob:
    def __init__(self):self.metadata={};self.size=0;self.content=None
    def exists(self):return self.content is not None
    def reload(self):pass
    def upload_from_filename(self,file,content_type,if_generation_match,timeout):
        assert if_generation_match==0
        self.content=Path(file).read_bytes();self.size=len(self.content)

class Bucket:
    def __init__(self):self.files={}
    def exists(self):return True
    def blob(self,key):return self.files.setdefault(key,Blob())

class Storage:
    def __init__(self):self.buckets={}
    def bucket(self,name):return self.buckets.setdefault(name,Bucket())

class TestSgsCloud(unittest.TestCase):
    def test_e2e_sgs_gcs_bigquery_idempotente(self):
        with tempfile.TemporaryDirectory() as d:
            storage=Storage()
            r=[]
            def loader(*,arquivo,project_id,dataset_id,executar):
                assert project_id=="nivon-data" and executar
                r.extend(json.loads(z) for z in Path(arquivo).read_text().splitlines())
                return {"executado":True}
            kwargs=dict(base=d,project_id="nivon-data",dataset_id="nivon_staging",
                bucket="nivon-raw-private",autorizacoes=OPS,
                evidencia="Uso de dados oficiais autorizado",
                executar=True,abridor=Abridor(),storage_client=storage,
                bq_loader=loader,instante=datetime(2026,10,23,12,tzinfo=timezone.utc))
            out=executar_sgs(**kwargs)
            self.assertTrue(out["bigquery_executado"])
            self.assertEqual(r[0]["dataset_id"],"BCB_SGS_TAXA_SELIC_DIARIA")
            self.assertEqual(r[0]["natureza"],"INFORMADO")
            self.assertEqual(r[0]["unidade"],"PERCENTUAL_AO_DIA")
            self.assertFalse(out["publicacao_automatica"])
            self.assertEqual(len(storage.bucket("nivon-raw-private").files),2)
            same=executar_sgs(**kwargs)
            self.assertEqual(same["coleta"]["novos"],0)

    def test_sgs_rejeita_sem_direitos(self):
        with tempfile.TemporaryDirectory() as d:
            with self.assertRaises(PermissionError):
                executar_sgs(base=d,project_id="nivon-data",
                    dataset_id="nivon_staging",bucket="x",
                    executar=True,abridor=Abridor())

    def test_sgs_parsing_conservador(self):
        with tempfile.TemporaryDirectory() as d:
            out=coletar_selic_diaria(
                banco=Path(d)/"db",raw_dir=Path(d)/"raw",
                executar=True,autorizacoes=OPS,abridor=Abridor(),
                instante=datetime(2026,10,23,12,tzinfo=timezone.utc))
            self.assertEqual(out["dataset"],"BCB_SGS_TAXA_SELIC_DIARIA")
            self.assertEqual(out["registros"],1)
            self.assertFalse(out["publicacao_automatica"])

if __name__=="__main__":
    unittest.main()
