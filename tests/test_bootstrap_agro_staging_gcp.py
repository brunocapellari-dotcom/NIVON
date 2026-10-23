"""Preflight/DDL único BQ: esquema privado sem promover IMEA/CONAB."""
import sys
import types
import unittest
from unittest.mock import patch
from nivon.agro_staging_bigquery import (
    verificar_ou_criar_tabela, TIPOS, ErroStagingAgro,
)


class NotFound(Exception):
    pass


class Table:
    def __init__(self,ref,schema):
        self.ref=ref
        self.schema=schema
        self.time_partitioning=None
        self.clustering_fields=[]
        self.description=""
        self.require_partition_filter=False


class Client:
    def __init__(self):
        self.table=None
        self.created=0
    def get_dataset(self,ref):
        assert ref=="nivon-data.nivon_raw"
        return types.SimpleNamespace(location="southamerica-east1")
    def get_table(self,ref):
        assert ref=="nivon-data.nivon_raw.agro_publicacoes_staging"
        if self.table is None:raise NotFound()
        return self.table
    def create_table(self,table,exists_ok):
        assert exists_ok is False
        self.table=table
        self.created+=1


def google_mock():
    bq=types.ModuleType("google.cloud.bigquery")
    bq.SchemaField=lambda k,t,mode="NULLABLE":types.SimpleNamespace(
        name=k,field_type=t,mode=mode)
    bq.Table=Table
    bq.TimePartitioningType=types.SimpleNamespace(DAY="DAY")
    bq.TimePartitioning=lambda type_,field:types.SimpleNamespace(type_=type_,field=field)
    cloud=types.ModuleType("google.cloud")
    cloud.bigquery=bq
    google=types.ModuleType("google")
    google.cloud=cloud
    api=types.ModuleType("google.api_core")
    exceptions=types.ModuleType("google.api_core.exceptions")
    exceptions.NotFound=NotFound
    api.exceptions=exceptions
    google.api_core=api
    return {"google":google,"google.cloud":cloud,
            "google.cloud.bigquery":bq,"google.api_core":api,
            "google.api_core.exceptions":exceptions}


class TestBootstrapAgro(unittest.TestCase):
    def test_planejamento_sem_acesso_cloud(self):
        result=verificar_ou_criar_tabela(
            projeto="nivon-data",dataset="nivon_raw")
        self.assertEqual(result["estado"],"PLANO_SEM_REDE")
        self.assertFalse(result["executado"])

    def test_sem_aprovacao_nao_cria(self):
        with self.assertRaises(PermissionError):
            verificar_ou_criar_tabela(
                projeto="nivon-data",dataset="nivon_raw",
                verificar=True,aplicar=True,aprovado=False)
        cli=Client()
        with patch.dict(sys.modules,google_mock()):
            out=verificar_ou_criar_tabela(
                projeto="nivon-data",dataset="nivon_raw",
                verificar=True,client=cli)
        self.assertEqual(out["estado"],"TABELA_AUSENTE")
        self.assertEqual(cli.created,0)

    def test_criacao_opt_in_sem_dataset_novo(self):
        cli=Client()
        with patch.dict(sys.modules,google_mock()):
            out=verificar_ou_criar_tabela(
                projeto="nivon-data",dataset="nivon_raw",
                verificar=True,aplicar=True,aprovado=True,client=cli)
            idem=verificar_ou_criar_tabela(
                projeto="nivon-data",dataset="nivon_raw",
                verificar=True,client=cli)
        self.assertTrue(out["criou_tabela"])
        self.assertFalse(idem["criou_tabela"])
        self.assertEqual(cli.created,1)
        self.assertEqual(cli.table.time_partitioning.field,"data_coleta")
        self.assertTrue(cli.table.require_partition_filter)
        self.assertEqual(cli.table.clustering_fields,
                         ["dataset_id","identidade","snapshot_id"])
        schema={x.name:x.field_type for x in cli.table.schema}
        self.assertEqual(schema,TIPOS)
        self.assertTrue(out["referencia_temporal_opcional"])

    def test_schema_diferente_recusado(self):
        cli=Client()
        cli.table=Table("nivon-data.nivon_raw.agro_publicacoes_staging",[])
        with patch.dict(sys.modules,google_mock()):
            with self.assertRaises(ErroStagingAgro):
                verificar_ou_criar_tabela(
                    projeto="nivon-data",dataset="nivon_raw",
                    verificar=True,client=cli)

if __name__=="__main__":
    unittest.main()
