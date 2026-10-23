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
    def query(self,sql,job_config=None):
        self.sql.append(sql)
        if job_config is None or getattr(job_config,"limit",0)!=100_000_000:
            raise AssertionError("limite de custos BigQuery nao aplicado")
        return FakeJob()
    def delete_table(self,target,not_found_ok):
        self.deleted.append(target)

class FakeBigQueryModule:
    class SchemaField:
        def __init__(self,name,kind):self.name,self.kind=name,kind
    class LoadJobConfig:
        def __init__(self,**args):self.config=args
    class QueryJobConfig:
        def __init__(self,maximum_bytes_billed):self.limit=maximum_bytes_billed
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

    def test_teto_de_faturamento_invalido_bloqueado_antes_de_qualquer_job(self):
        with self.assertRaises(ValueError):
            sincronizar_bigquery("/tmp/nao-existe.sqlite",projeto="nivon-data",
                  dataset="nivon_raw",max_bytes_cobraveis=100_000_000_000)
        with self.assertRaises(ValueError):
            sincronizar_bigquery("/tmp/nao-existe.sqlite",projeto="nivon-data",
                  dataset="nivon_raw",max_bytes_cobraveis=True)

    def test_localizacao_invalida_bloqueada_antes_de_rede(self):
        with self.assertRaises(ValueError):
            sincronizar_bigquery("/tmp/arquivo-ausente.sqlite",projeto="nivon-data",
                dataset="nivon_raw",localizacao="US;drop")

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

    def test_manifesto_corrompido_bloqueia_replay(self):
        from nivon.maritimo_replay_gcp import reprocessar_manifesto
        storage=FakeStorage()
        result=executar_job(env={
            "NIVON_MARITIMO_COLETA_HABILITADA":"true",
            "GOOGLE_CLOUD_PROJECT":"nivon-exemplo-123",
            "NIVON_MARITIMO_BUCKET":"bucket-nivon-123",
        },storage_client=storage,bigquery_client=FakeBigQueryClient(),
           bigquery_module=FakeBigQueryModule,fornecedor_html=lambda _:HTML)
        bucket=storage.bucket("bucket-nivon-123")
        name=next(k for k in bucket.blobs if "_manifestos/" in k)
        bucket.blobs[name].content=b'{"schema_version": 1, "tampered": true}'
        with self.assertRaisesRegex(ValueError,"hash"):
            reprocessar_manifesto(bucket="bucket-nivon-123",uri=result["manifesto"],
              projeto="nivon-exemplo-123",storage_client=storage,
              bigquery_client=FakeBigQueryClient(),
              bigquery_module=FakeBigQueryModule)

    def test_projeto_ausente_bloqueia_antes_de_gcs(self):
        storage=FakeStorage()
        with self.assertRaises(ValueError):
            executar_job(env={
                "NIVON_MARITIMO_COLETA_HABILITADA":"true",
                "NIVON_MARITIMO_BUCKET":"bucket-nivon-123",
            },storage_client=storage,bigquery_client=FakeBigQueryClient(),
               bigquery_module=FakeBigQueryModule,fornecedor_html=lambda _:HTML)
        self.assertEqual(storage.buckets,{})

    def test_reutiliza_contrato_cloud_de_fontes_nivon(self):
        storage=FakeStorage()
        client=FakeBigQueryClient()
        report=executar_job(env={
            "NIVON_MARITIMO_COLETA_HABILITADA":"true",
            "NIVON_BQ_PROJECT":"nivon-data",
            "NIVON_BQ_DATASET":"nivon_raw",
            "NIVON_GCS_BUCKET":"nivon-data-raw-2026",
        },storage_client=storage,bigquery_client=client,
           bigquery_module=FakeBigQueryModule,fornecedor_html=lambda _:HTML)
        self.assertTrue(report["persistencia"]["gravado"])
        self.assertEqual(report["persistencia"]["destino"],"nivon-data.nivon_raw")
        self.assertTrue(storage.bucket("nivon-data-raw-2026").blobs)

    def test_cloud_run_desabilitado_sem_qualquer_escrita(self):
        with self.assertRaises(PermissionError):
            executar_job(env={"GOOGLE_CLOUD_PROJECT":"nivon-exemplo-123"},
                        storage_client=FakeStorage(),bigquery_client=FakeBigQueryClient())

    def test_replay_gcs_faz_bigquery_idempotente_sem_consultar_fonte(self):
        from nivon.maritimo_replay_gcp import reprocessar_manifesto
        storage=FakeStorage()
        first=FakeBigQueryClient()
        original=executar_job(env={
            "NIVON_MARITIMO_COLETA_HABILITADA":"true",
            "GOOGLE_CLOUD_PROJECT":"nivon-exemplo-123",
            "NIVON_MARITIMO_BUCKET":"bucket-nivon-123",
            "NIVON_PORTWATCH_COLETA_HABILITADA":"true",
        },storage_client=storage,bigquery_client=first,
           bigquery_module=FakeBigQueryModule,
           fornecedor_html=lambda _:HTML,fornecer_portwatch=PORTWATCH)
        resumed=FakeBigQueryClient()
        retry=reprocessar_manifesto(bucket="bucket-nivon-123",
          uri=original["manifesto"],projeto="nivon-exemplo-123",
          storage_client=storage,bigquery_client=resumed,
          bigquery_module=FakeBigQueryModule)
        self.assertEqual(retry["fontes_reprocessadas"],4)
        self.assertEqual(retry["linhas_portwatch"],1)
        self.assertEqual(len(resumed.sql),4)
        self.assertTrue(all("MERGE" in sql for sql in resumed.sql))
        self.assertFalse(next(row for target,rows,_ in resumed.loads
                             for row in rows if row.get("fonte")=="santarem_cdp"
                             and "publicavel" in row)["publicavel"])

    def test_snapshot_com_hash_adulterado_e_rejeitado(self):
        from nivon.maritimo_replay_gcp import reprocessar_manifesto
        storage=FakeStorage()
        result=executar_job(env={
            "NIVON_MARITIMO_COLETA_HABILITADA":"true",
            "GOOGLE_CLOUD_PROJECT":"nivon-exemplo-123",
            "NIVON_MARITIMO_BUCKET":"bucket-nivon-123",
        },storage_client=storage,bigquery_client=FakeBigQueryClient(),
           bigquery_module=FakeBigQueryModule,fornecedor_html=lambda _:HTML)
        bucket=storage.bucket("bucket-nivon-123")
        name=next(k for k in bucket.blobs if "/imbituba/" in k)
        bucket.blobs[name].content=b"invalid"
        with self.assertRaises(ValueError):
            reprocessar_manifesto(bucket="bucket-nivon-123",uri=result["manifesto"],
                projeto="nivon-exemplo-123",storage_client=storage,
                bigquery_client=FakeBigQueryClient(),bigquery_module=FakeBigQueryModule)

if __name__=="__main__":
    unittest.main()
