"""Execução simulada do MERGE BigQuery: confirma SQL, schema e cleanup."""
import json
import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest.mock import patch

from nivon.carga_bigquery_fontes import executar_carga, ErroCargaBigQuery


class FakeJob:
    def __init__(self,bytes_processados=1024):
        self.total_bytes_processed=bytes_processados
    def result(self,timeout=None):
        return self


class FakeClient:
    def __init__(self,bytes_processados=1024):
        self.sql=None
        self.stage_bytes=0
        self.deleted=False
        self.bytes_processados=bytes_processados
        self.queries=[]
    def get_dataset(self, ref):
        assert ref=="nivon-data.agro"
    def get_table(self, ref):
        assert ref=="nivon-data.agro.nivon_observacoes"
        schema=[types.SimpleNamespace(name=n,field_type=t)
                for n,t in (("data_referencia","DATE"),
                            ("data_coleta","TIMESTAMP"),
                            ("data_publicacao","TIMESTAMP"))]
        return types.SimpleNamespace(schema=schema)
    def load_table_from_file(self, fileobj, table, job_config=None):
        self.stage_bytes=len(fileobj.read())
        assert self.stage_bytes>0 and "._nivon_stage_" in table
        return FakeJob()
    def query(self, sql, job_config=None):
        self.sql=sql
        assert job_config is not None
        self.queries.append(job_config)
        if getattr(job_config,"dry_run",False):
            return FakeJob(self.bytes_processados)
        return FakeJob()
    def delete_table(self, name, not_found_ok=False):
        assert not_found_ok
        self.deleted=True


def modulos_gcp():
    bigquery=types.ModuleType("google.cloud.bigquery")
    bigquery.SourceFormat=types.SimpleNamespace(NEWLINE_DELIMITED_JSON="JSONL")
    bigquery.WriteDisposition=types.SimpleNamespace(WRITE_TRUNCATE="WRITE_TRUNCATE")
    bigquery.LoadJobConfig=lambda **kw: types.SimpleNamespace(**kw)
    bigquery.QueryJobConfig=lambda **kw: types.SimpleNamespace(**kw)
    bigquery.SchemaField=lambda name,t: types.SimpleNamespace(name=name,field_type=t)
    bigquery.ScalarQueryParameter=lambda name,t,value: types.SimpleNamespace(name=name,type_=t,value=value)
    cloud=types.ModuleType("google.cloud")
    cloud.bigquery=bigquery
    google=types.ModuleType("google")
    google.cloud=cloud
    return {"google":google,"google.cloud":cloud,"google.cloud.bigquery":bigquery}


class BigQueryMERGETest(unittest.TestCase):
    def test_merge_temporal_e_cleanup(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/"stage.jsonl"
            row={
                "dataset_id":"ARG_BCRA_V1","identidade":"BCRA_1|2026-10-01",
                "fingerprint":"a"*64,"referencia":"2026-10-01",
                "competencia":None,"publicacao":None,
                "coletado_em":"2026-10-23T03:22:18+00:00",
                "unidade":None,"valor":"42","campos":{"x":42},
                "snapshot_id":"b"*64,"natureza":"INFORMADO"}
            p.write_text(json.dumps(row)+"\n",encoding="utf-8")
            client=FakeClient()
            with patch.dict(sys.modules,modulos_gcp()):
                result=executar_carga(arquivo=p,project_id="nivon-data",
                  dataset_id="agro",executar=True,client=client)
            self.assertTrue(result["executado"])
            self.assertTrue(client.deleted)
            self.assertIn("data_referencia",client.sql)
            self.assertIn("CAST(S.referencia AS DATE)",client.sql)
            self.assertIn("CAST(S.coletado_em AS TIMESTAMP)",client.sql)
            self.assertIn("MERGE `nivon-data.agro.nivon_observacoes`",client.sql)
            self.assertIn("fingerprint",client.sql)
            self.assertIn("T.data_referencia BETWEEN @ref_inicio AND @ref_fim",client.sql)
            self.assertIn("T.data_referencia = CAST(S.referencia AS DATE)",client.sql)
            self.assertEqual(result["referencia_inicio"],"2026-10-01")
            self.assertEqual(result["referencia_fim"],"2026-10-01")
            self.assertEqual(result["bytes_estimados"],1024)
            self.assertEqual(len(client.queries),2)
            self.assertTrue(client.queries[0].dry_run)
            self.assertEqual(client.queries[1].maximum_bytes_billed,10_000_000)
            self.assertEqual(
                {p.name for p in client.queries[1].query_parameters},
                {"ref_inicio","ref_fim"})



    def test_dry_run_acima_do_limite_bloqueia_e_limpa_stage(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/"stage.jsonl"
            row={
                "dataset_id":"BR_CCEE_PLD_HORARIO","identidade":"2026|NORDESTE|23|00",
                "fingerprint":"a"*64,"referencia":"2026-10-23",
                "competencia":"202610","publicacao":None,
                "coletado_em":"2026-10-23T04:00:00+00:00",
                "unidade":"R$/MWh","valor":"60",
                "campos":{"submercado":"NORDESTE"},"snapshot_id":"b"*64,
                "natureza":"INFORMADO"}
            p.write_text(json.dumps(row)+"\n",encoding="utf-8")
            for estimate in (10_000_001,None):
                with self.subTest(estimate=estimate):
                    client=FakeClient(bytes_processados=estimate)
                    with patch.dict(sys.modules,modulos_gcp()):
                        with self.assertRaises(ErroCargaBigQuery):
                            executar_carga(arquivo=p,project_id="nivon-data",
                               dataset_id="agro",executar=True,client=client)
                    self.assertTrue(client.deleted)
                    self.assertEqual(len(client.queries),1)
                    self.assertTrue(client.queries[0].dry_run)

if __name__=="__main__":
    unittest.main()
