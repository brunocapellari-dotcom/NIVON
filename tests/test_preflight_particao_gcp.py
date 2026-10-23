"""Bootstrap BigQuery canônico: schema, região, partição e IAM sem criação implícita."""
from __future__ import annotations
import sys
import types
import unittest
from unittest.mock import patch
from nivon.preflight_gcp_fontes import verificar_nuvem,STAGE,CANONICOS
from nivon.carga_bigquery_fontes import ErroCargaBigQuery


class NotFound(Exception): pass


def tabela(part_filter=True):
    return types.SimpleNamespace(
        schema=[types.SimpleNamespace(name=k,field_type=v) for k,v in STAGE+CANONICOS],
        time_partitioning=types.SimpleNamespace(field="data_referencia"),
        clustering_fields=["dataset_id","identidade","fingerprint"],
        require_partition_filter=part_filter)


class FakeBQ:
    def __init__(self,existente=None,regiao="southamerica-east1"):
        self.table=existente
        self.region=regiao
        self.created=0
    def get_dataset(self,ref):
        assert ref=="nivon-data.nivon_raw"
        return types.SimpleNamespace(location=self.region,project="nivon-data",
                                     dataset_id="nivon_raw")
    def get_table(self,ref):
        if self.table is None:raise NotFound(ref)
        return self.table
    def create_table(self,tab,exists_ok):
        assert exists_ok is True
        self.created+=1
        self.table=tab
        return tab


class Bucket:
    def exists(self,client=None):
        return True


class FakeGCS:
    def bucket(self,name):
        assert name=="nivon-data-raw-2026"
        return Bucket()


def sdk():
    cloud=types.ModuleType("google.cloud")
    bq=types.ModuleType("google.cloud.bigquery")
    bq.SchemaField=lambda nome,tipo,mode:types.SimpleNamespace(
        name=nome,field_type=tipo,mode=mode)
    bq.Table=lambda name,schema:types.SimpleNamespace(
        name=name,schema=schema,clustering_fields=[],
        time_partitioning=None,require_partition_filter=False)
    bq.TimePartitioningType=types.SimpleNamespace(DAY="DAY")
    bq.TimePartitioning=lambda type_,field:types.SimpleNamespace(
        type_=type_,field=field)
    st=types.ModuleType("google.cloud.storage")
    cloud.bigquery=bq
    cloud.storage=st
    google=types.ModuleType("google")
    google.cloud=cloud
    api=types.ModuleType("google.api_core")
    exc=types.ModuleType("google.api_core.exceptions")
    exc.NotFound=NotFound
    api.exceptions=exc
    return {"google":google,"google.cloud":cloud,"google.cloud.bigquery":bq,
            "google.cloud.storage":st,"google.api_core":api,
            "google.api_core.exceptions":exc}


class TestPreflightSchemaRealista(unittest.TestCase):
    def check(self,client,criar=False):
        with patch.dict(sys.modules,sdk()):
            return verificar_nuvem(
                projeto="nivon-data",dataset="nivon_raw",
                bucket="nivon-data-raw-2026",
                criar_tabela=criar,client_bq=client,client_storage=FakeGCS())

    def test_cria_so_quando_explicito_com_filtro_obrigatorio(self):
        c=FakeBQ()
        with self.assertRaises(ErroCargaBigQuery):
            self.check(c)
        self.assertEqual(c.created,0)
        out=self.check(c,True)
        self.assertTrue(out["tabela_criada"])
        self.assertEqual(c.created,1)
        self.assertTrue(c.table.require_partition_filter)
        self.assertEqual(c.table.clustering_fields,
                         ["dataset_id","identidade","fingerprint"])
        self.assertFalse(self.check(c)["tabela_criada"])

    def test_rejeita_tabela_existente_sem_filtro(self):
        with self.assertRaises(ErroCargaBigQuery):
            self.check(FakeBQ(tabela(part_filter=False)))

    def test_rejeita_dataset_fora_da_regiao_sem_criar(self):
        c=FakeBQ(regiao="us-central1")
        with self.assertRaises(ErroCargaBigQuery):
            self.check(c,True)
        self.assertEqual(c.created,0)

if __name__=="__main__":
    unittest.main()
