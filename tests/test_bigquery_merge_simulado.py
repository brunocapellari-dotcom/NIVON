"""Execução simulada do MERGE BigQuery: confirma SQL, schema e cleanup."""
import json
import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest.mock import patch

from nivon.carga_bigquery_fontes import executar_carga


class FakeJob:
    def result(self,timeout=None):
        return self


class FakeClient:
    def __init__(self):
        self.sql=None
        self.stage_bytes=0
        self.deleted=False
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

if __name__=="__main__":
    unittest.main()
