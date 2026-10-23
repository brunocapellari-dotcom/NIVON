"""E2E local Google Cloud: GCS -> staging -> BigQuery, sem rede nem credenciais."""
import hashlib
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from nivon.maritimo_cloud_storage import ArquivoMaritimoGCS
from nivon.maritimo_bigquery import (
    sincronizar_bigquery,preparar_linhas,sql_merge,validar_destino
)
from nivon.maritimo_pipeline import HistoricoMaritimo, processar_html
from nivon.maritimo_lote import executar_lote
from nivon.maritimo_gcp_job import executar_job

HTML=("<h3>Programacao</h3><table><tr><th>Navio</th><th>Berco</th>"
      "<th>Situacao</th><th>Chegada</th></tr><tr>"
      "<td>TEST VESSEL</td><td>2</td><td>Esperado</td><td>23/10/2026</td>"
      "</tr></table>")
PORTWATCH=json.dumps({"features":[{"attributes":{
 "portname":"Suez Canal","portid":"TESTPORT1","date":"2026-10-20",
 "n_total":11,"n_dry_bulk":5,"n_tanker":3,"capacity":92000}}]}).encode()

class FakeBlob:
    def __init__(self,name):
        self.name=name
        self.metadata={}
        self.content=None
        self.calls=0
    def upload_from_string(self,raw,content_type=None,if_generation_match=None):
        self.calls+=1
        assert if_generation_match==0
        self.content=raw
    def reload(self):pass
    def download_as_bytes(self):
        if self.content is None:raise FileNotFoundError(self.name)
        return self.content

class FakeBucket:
    def __init__(self):self.blobs={}
    def blob(self,name):
        return self.blobs.setdefault(name,FakeBlob(name))

class FakeStorage:
    def __init__(self):self.buckets={}
    def bucket(self,name):return self.buckets.setdefault(name,FakeBucket())

class FakeJob:
    def result(self):return self

class FakeBigQueryClient:
    def __init__(self):
        self.loads=[]
        self.sql=[]
        self.deleted=[]
    def load_table_from_json(self,rows,target,job_config):
        self.loads.append((target,rows,job_config))
        return FakeJob()
    def query(self,sql):
        self.sql.append(sql)
        return FakeJob()
    def delete_table(self,target,not_found_ok):
        self.deleted.append(target)

class FakeBigQueryModule:
    class SchemaField:
        def __init__(self,name,kind):self.name,self.kind=name,kind
    class LoadJobConfig:
        def __init__(self,**args):self.config=args
    class SourceFormat:
        NEWLINE_DELIMITED_JSON="NEWLINE_DELIMITED_JSON"
    class WriteDisposition:
        WRITE_EMPTY="WRITE_EMPTY"

class TestCloud(unittest.TestCase):
    def test_bigquery_dryrun_sem_import_google(self):
        with tempfile.TemporaryDirectory() as d:
            local=Path(d)/"historico.sqlite"
            repo=HistoricoMaritimo(local)
            processar_html("santarem_cdp",HTML,repo,coletado_em="2026-10-23T11:00:00Z")
            repo.fechar()
            report=sincronizar_bigquery(local,projeto="nivon-exemplo-123",
                dataset="nivon_maritimo",dry_run=True)
            self.assertEqual(report["contagens"]["escalas_revisoes"],1)
            self.assertFalse(report["gravado"])
            rows=preparar_linhas(local)
            self.assertFalse(rows["escalas_revisoes"][0]["publicavel"])
            self.assertEqual(rows["escalas_revisoes"][0]["competencia"],"2026-10")

    def test_replay_usa_merge_e_limpeza_staging(self):
        with tempfile.TemporaryDirectory() as d:
            local=Path(d)/"h.sqlite"
            repo=HistoricoMaritimo(local)
            executar_lote(("suape","santarem_cdp"),repo,coletado_em="2026-10-23T11:00:00Z",
                           fornecedor_html=lambda _:HTML)
            repo.fechar()
            fake=FakeBigQueryClient()
            out=sincronizar_bigquery(local,projeto="nivon-exemplo-123",
              client=fake,bigquery_module=FakeBigQueryModule)
            self.assertTrue(out["gravado"])
            self.assertEqual(len(fake.loads),3)
            self.assertEqual(len(fake.deleted),3)
            self.assertEqual(len(fake.sql),3)
            self.assertTrue(all("MERGE" in s and "INSERT ROW" in s for s in fake.sql))
            self.assertFalse(next(r for r in fake.loads[1][1] if r["fonte"]=="santarem_cdp")["publicavel"])

    def test_bigquery_injection_rejeitada(self):
        for bad in ["other.project","a;delete","x"]:
            with self.assertRaises(ValueError):
                validar_destino(bad,"nivon_maritimo")
        with self.assertRaises(ValueError):
            sql_merge("nivon-exemplo-123","nivon_maritimo","invalida","_staging_xyz_0123456789abcdef")

    def test_gcs_arquiva_com_sha_e_precondicao(self):
        storage=FakeStorage()
        archive=ArquivoMaritimoGCS("bucket-nivon-123",storage_client=storage)
        out=archive.arquivar("imbituba",HTML,coletado_em="2026-10-23T11:00:00Z")
        self.assertIn(hashlib.sha256(HTML.encode()).hexdigest(),out["uri"])
        objects=storage.bucket("bucket-nivon-123").blobs
        self.assertEqual(len(objects),1)
        self.assertEqual(next(iter(objects.values())).content,HTML.encode("utf-8"))
        with self.assertRaises(ValueError):
            archive.arquivar("../escape",HTML,coletado_em="2026-10-23T11:00:00Z")

    def test_cloud_run_end_to_end_com_evidencias(self):
        storage=FakeStorage()
        client=FakeBigQueryClient()
        result=executar_job(env={
            "NIVON_MARITIMO_COLETA_HABILITADA":"true",
            "GOOGLE_CLOUD_PROJECT":"nivon-exemplo-123",
            "NIVON_MARITIMO_BUCKET":"bucket-nivon-123",
            "NIVON_MARITIMO_DATASET":"nivon_maritimo",
            "NIVON_PORTWATCH_COLETA_HABILITADA":"true",
        },storage_client=storage,bigquery_client=client,bigquery_module=FakeBigQueryModule,
          fornecedor_html=lambda _:HTML,fornecer_portwatch=PORTWATCH)
        self.assertTrue(result["apto_operacao"])
        self.assertEqual(result["estados"],{"OK":2,"QUARENTENA":2,"FALHA":0})
        self.assertEqual(result["persistencia"]["contagens"]["fluxos_passagens"],1)
        self.assertEqual(len(client.sql),4)
        self.assertEqual(len(storage.bucket("bucket-nivon-123").blobs),6)
        self.assertIn("/_manifestos/",result["manifesto"])

    def test_cloud_run_desabilitado_sem_qualquer_escrita(self):
        with self.assertRaises(PermissionError):
            executar_job(env={"GOOGLE_CLOUD_PROJECT":"nivon-exemplo-123"},
                        storage_client=FakeStorage(),bigquery_client=FakeBigQueryClient())

if __name__=="__main__":
    unittest.main()
