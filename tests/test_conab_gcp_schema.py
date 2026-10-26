"""Contratos do bootstrap da tabela CONAB BigQuery; clientes simulados."""
from types import SimpleNamespace
from unittest import TestCase

from nivon.agro_bigquery_loader import _TIPOS
from nivon.conab_gcp_schema import verificar_ou_criar,ErroSchemaConab

class NaoExiste(Exception):pass

class FakeSDK:
    TimePartitioningType=SimpleNamespace(DAY='DAY')
    @staticmethod
    def SchemaField(name,field_type,mode):
        return SimpleNamespace(name=name,field_type=field_type)
    @staticmethod
    def TimePartitioning(*,type_,field):
        return SimpleNamespace(type_=type_,field=field)
    @staticmethod
    def Table(ref,schema):
        return SimpleNamespace(schema=schema,location='southamerica-east1',
                time_partitioning=None,clustering_fields=[],description='',ref=ref)

class Client:
    def __init__(self):
        self.vezes=0
        self.table=None
    def get_dataset(self,ref):
        assert ref=='nivon-data.nivon_raw'
        return SimpleNamespace(location='southamerica-east1')
    def get_table(self,ref):
        assert ref=='nivon-data.nivon_raw.agro_fonte_stage'
        if self.table is None: raise NaoExiste()
        return self.table
    def create_table(self,t,exists_ok):
        assert exists_ok is False
        self.vezes+=1
        self.table=t
        return t

class TestSchemaConab(TestCase):
    def setUp(self):self.db=Client()
    def kw(self,**overrides):
        return dict(projeto='nivon-data',dataset='nivon_raw',
                    cliente=self.db,sdk=FakeSDK,not_found=NaoExiste,**overrides)

    def test_diagnostico_nao_cria(self):
        r=verificar_ou_criar(**self.kw())
        self.assertEqual(r['status'],'TABELA_STAGE_AUSENTE_SEM_CRIACAO')
        self.assertEqual(self.db.vezes,0)

    def test_sem_gate_nao_cria(self):
        with self.assertRaises(PermissionError):
            verificar_ou_criar(**self.kw(aplicar=True))
        self.assertEqual(self.db.vezes,0)

    def test_criar_uma_tabela_existente_nao_duplica(self):
        args=self.kw(aplicar=True,schema_aprovado=True,custos_autorizados=True)
        r=verificar_ou_criar(**args)
        self.assertTrue(r['criada'])
        self.assertEqual(r['colunas'],len(_TIPOS))
        self.assertEqual(self.db.table.time_partitioning.field,'coletado_utc')
        r2=verificar_ou_criar(**args)
        self.assertFalse(r2['criada'])
        self.assertEqual(self.db.vezes,1)

    def test_erro_schema_silencioso_recusado(self):
        verificar_ou_criar(**self.kw(aplicar=True,schema_aprovado=True,custos_autorizados=True))
        self.db.table.schema[0]=SimpleNamespace(name='outro',field_type='STRING')
        with self.assertRaises(ErroSchemaConab):
            verificar_ou_criar(**self.kw())

    def test_projeto_malformado_recusado_sem_api(self):
        with self.assertRaises(ErroSchemaConab):
            verificar_ou_criar(**self.kw(projeto='evil-project.example.org'))

if __name__=='__main__':
    import unittest
    unittest.main()
