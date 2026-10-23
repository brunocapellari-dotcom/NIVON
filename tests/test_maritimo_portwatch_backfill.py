"""Retrocarga por janelas limitadas, snapshots e MERGE com identidades simuladas."""
import unittest
from nivon.maritimo_portwatch_backfill import janelas, retrocarregar

class FakeBlob:
    def __init__(self,name):self.name=name;self.metadata={};self.data=None
    def upload_from_string(self,raw,**kwargs):self.data=raw
    def download_as_bytes(self):return self.data
    def reload(self):pass

class FakeBucket:
    def __init__(self):self.store={}
    def blob(self,k):
        if k not in self.store:self.store[k]=FakeBlob(k)
        return self.store[k]

class FakeStorage:
    def __init__(self):self.buckets={}
    def bucket(self,k):
        return self.buckets.setdefault(k,FakeBucket())

class FakeJob:
    def result(self):return self

class FakeClient:
    def __init__(self):self.loads=[];self.queries=[]
    def load_table_from_json(self,rows,table,job_config):
        self.loads.append((table,rows))
        return FakeJob()
    def query(self,sql,job_config=None):
        self.queries.append(sql)
        if job_config is None or getattr(job_config,"limit",None)!=100_000_000:
            raise AssertionError("sem teto BigQuery")
        return FakeJob()
    def delete_table(self,*args,**kwargs):pass

class FakeBQ:
    class SchemaField:
        def __init__(self,*args):pass
    class LoadJobConfig:
        def __init__(self,**kwargs):pass
    class QueryJobConfig:
        def __init__(self,maximum_bytes_billed):self.limit=maximum_bytes_billed
    class SourceFormat:
        NEWLINE_DELIMITED_JSON="NEWLINE_DELIMITED_JSON"
    class WriteDisposition:
        WRITE_EMPTY="WRITE_EMPTY"

class Retrocarga(unittest.TestCase):
    def test_intervalos_sem_sobreposicao(self):
        spans=janelas("2019-01-01","2019-03-03")
        self.assertEqual(spans,[("2019-01-01","2019-01-31"),
                                ("2019-02-01","2019-03-03")])
        with self.assertRaises(ValueError):
            janelas("2019-01-01","2020-01-01")
        with self.assertRaises(ValueError):
            janelas("2018-01-01","2019-01-01")

    def test_retrocarrega_replay_do_primeiro_periodo(self):
        import json
        from nivon.maritimo_replay_gcp import reprocessar_manifesto
        payload=json.dumps({"features":[{"attributes":{
          "portname":"Suez Canal","portid":"CHOKEPOINT_TEST",
          "date":"2019-01-14","n_total":10,"n_dry_bulk":3,
          "n_tanker":6,"capacity":455000
        }}]}).encode()
        storage=FakeStorage()
        client=FakeClient()
        opts=dict(inicio="2019-01-01",fim="2019-01-31",
          projeto="nivon-exemplo-123",bucket="bucket-nivon-123",
          env={"NIVON_PORTWATCH_BACKFILL_HABILITADO":"true"},
          storage_client=storage,bigquery_client=client,
          bigquery_module=FakeBQ,fornecer_pagina=payload)
        reports=retrocarregar(**opts)
        self.assertEqual(len(reports),1)
        self.assertTrue(reports[0]["gravado"])
        self.assertEqual(reports[0]["registros"],1)
        self.assertEqual(len(client.queries),2)
        new=FakeClient()
        recovery=reprocessar_manifesto(
          bucket="bucket-nivon-123",uri=reports[0]["manifesto"],
          projeto="nivon-exemplo-123",storage_client=storage,
          bigquery_client=new,bigquery_module=FakeBQ)
        self.assertEqual(recovery["linhas_portwatch"],1)
        self.assertEqual(len(new.queries),2)

    def test_sem_autorizacao_nao_inicia(self):
        with self.assertRaises(PermissionError):
            retrocarregar(inicio="2019-01-01",fim="2019-01-31",
             projeto="nivon-exemplo-123",bucket="bucket-nivon-123",
             env={},storage_client=FakeStorage())
if __name__=="__main__":
    unittest.main()
