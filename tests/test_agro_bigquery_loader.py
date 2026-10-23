"""BigQuery staging: preflight e job mock, sem conexoes GCP."""
import json
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest import TestCase

from nivon.agro_bigquery_loader import (
    ErroUploadAgro,_FIELDS,_TIPOS,validar_lote,carregar_bigquery
)

class NaoEncontrado(Exception):pass

class BigQueryFake:
    SourceFormat=SimpleNamespace(NEWLINE_DELIMITED_JSON='NEWLINE_DELIMITED_JSON')
    WriteDisposition=SimpleNamespace(WRITE_APPEND='WRITE_APPEND')
    @staticmethod
    def LoadJobConfig(**kw):return SimpleNamespace(**kw)

class JobFake:
    def __init__(self,tabela):self.destination=tabela;self.error_result=None
    def result(self,timeout):return self

class ClientFake:
    def __init__(self,tabela):self.tabela=tabela;self.jobs={};self.loads=0
    def get_table(self,table):
        assert table==self.tabela
        return SimpleNamespace(schema=[SimpleNamespace(name=k,field_type=v) for k,v in _TIPOS.items()],
                               location='southamerica-east1')
    def get_job(self,id,location):
        if id not in self.jobs:raise NaoEncontrado()
        return self.jobs[id]
    def load_table_from_file(self,file,*,destination,job_config,job_id,location):
        assert destination==self.tabela
        assert location=='southamerica-east1'
        assert job_config.write_disposition=='WRITE_APPEND'
        self.loads+=1
        self.jobs[job_id]=JobFake(destination)
        return self.jobs[job_id]


class TestBigQueryLoader(TestCase):
    def setUp(self):
        self.context=TemporaryDirectory()
        self.addCleanup(self.context.cleanup)
        self.root=Path(self.context.name)/'privado'
        self.root.mkdir(mode=0o700)
        self.file=self.root/'dados.jsonl'
        self.tabela='nivon-data.nivon_stage.agro_fonte_stage'
        obj={k:('2026-10-22T20:00:00+00:00' if k=='coletado_utc'
                else 'b'*64 if k=='source_sha256'
                else '12.5' if k=='valor'
                else 'QUARENTENA_NAO_PUBLICAVEL' if k=='status'
                else None if k in {'safra','data_publicacao_original','regiao','competencia'}
                else 'test') for k in _FIELDS}
        self.file.write_text(json.dumps(obj)+'\n')
        self.file.chmod(0o600)
        self.client=ClientFake(self.tabela)

    def test_preflight_nao_acessa_cloud(self):
        r=carregar_bigquery(arquivo=self.file,projeto='nivon-data',dataset='nivon_stage')
        self.assertFalse(r['job_executado'])
        self.assertEqual(r['status'],'PREFLIGHT_LOCAL_SEM_CLOUD')
        self.assertEqual(self.client.loads,0)

    def test_gates_antes_credenciais(self):
        with self.assertRaises(PermissionError):
            carregar_bigquery(arquivo=self.file,projeto='nivon-data',
                              dataset='nivon_stage',executar=True)
        self.assertEqual(self.client.loads,0)

    def test_execucao_mock_idempotente(self):
        kw=dict(arquivo=self.file,projeto='nivon-data',dataset='nivon_stage',
                executar=True,custos_autorizados=True,armazenamento_autorizado=True,
                licencas_conferidas=True,cliente=self.client,tipos_bq=BigQueryFake,
                tipo_nao_encontrado=NaoEncontrado)
        primeiro=carregar_bigquery(**kw)
        segundo=carregar_bigquery(**kw)
        self.assertTrue(primeiro['job_executado'])
        self.assertFalse(segundo['job_executado'])
        self.assertEqual(self.client.loads,1)
        self.assertEqual(primeiro['job_id'],segundo['job_id'])
        self.assertIn('EXISTENTE',segundo['status'])

    def test_schema_errado_nao_submete(self):
        self.client.get_table=lambda table: SimpleNamespace(
            schema=[SimpleNamespace(name='errado',field_type='STRING')],
            location='southamerica-east1')
        with self.assertRaises(ErroUploadAgro):
            carregar_bigquery(arquivo=self.file,projeto='nivon-data',
                              dataset='nivon_stage',executar=True,custos_autorizados=True,
                              armazenamento_autorizado=True,licencas_conferidas=True,
                              cliente=self.client,tipos_bq=BigQueryFake,
                              tipo_nao_encontrado=NaoEncontrado)

    def test_linha_fora_do_contrato_nao_envia(self):
        self.file.write_text('{"x":1}\n')
        with self.assertRaises(ErroUploadAgro):
            validar_lote(self.file)
        self.assertEqual(self.client.loads,0)


if __name__=='__main__':
    import unittest
    unittest.main()
