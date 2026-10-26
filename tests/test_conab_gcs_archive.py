"""Testes de escrita imutável GCS sem rede, contas Google ou custos."""
from hashlib import sha256
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase
from unittest.mock import patch

from nivon.conab_gcs_archive import (
    _guardar,arquivar_lote,ErroArquivoConabGCS
)


class JaExistente(Exception):pass


class BlobFake:
    def __init__(self,bucket,name):
        self.bucket=bucket
        self.name=name
        self.metadata={}
    def upload_from_string(self,data,*,content_type,if_generation_match):
        assert if_generation_match==0
        if self.name in self.bucket.objetos:
            raise JaExistente()
        self.bucket.objetos[self.name]=(bytes(data),dict(self.metadata),content_type)
    def reload(self):
        self.metadata=dict(self.bucket.objetos[self.name][1])
    def download_as_bytes(self):
        data=self.bucket.objetos[self.name][0]
        if self.bucket.corromper:return b'corrompido'
        return data


class BucketFake:
    def __init__(self,name):
        self.name=name
        self.location='southamerica-east1'
        self.objetos={}
        self.corromper=False
    def blob(self,name):return BlobFake(self,name)


class ClienteFake:
    def __init__(self,bucket):self.b=bucket
    def get_bucket(self,name):
        assert name==self.b.name
        return self.b


class TestArquivoConabGCS(TestCase):
    def setUp(self):
        self.bucket=BucketFake('nivon-data-raw-2026')
        self.cliente=ClienteFake(self.bucket)
        self.temp=TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name)
        self.raw=self.root/'raw.xlsx'
        self.raw.write_bytes(b'PK-raw-fixture-sintetica')
        self.ev=self.root/'evidencia.json'
        self.ev.write_bytes(b'{"fixture":true}')
        self.digest=sha256(self.raw.read_bytes()).hexdigest()
        self.path=f'nivon/conab/progresso/v1/CONAB_PROG_2026_10_18/{self.digest}'
        self.item={'id_edicao':'CONAB_PROG_2026_10_18',
                   'sha256_raw':self.digest,
                   'coletado_utc':'2026-10-23T13:00:00+00:00',
                   'raw':str(self.raw),'evidencia':str(self.ev),
                   'observacoes':58,
                   'uri_raw':f'gs://{self.bucket.name}/{self.path}/raw.xlsx',
                   'uri_evidencia':f'gs://{self.bucket.name}/{self.path}/evidencia.json'}
        self.plano={'total_edicoes':1,'edicoes':[self.item],
                    'status':'PREFLIGHT_LOCAL_GCS_SEM_ESCRITA'}

    def _executar(self,**overrides):
        args=dict(banco='nao-acessado-no-mock',raw_dir='privado',
            bucket=self.bucket.name,executar=True,
            direitos_armazenamento=True,custos_autorizados=True,
            cliente=self.cliente,precondition_failed=JaExistente)
        args.update(overrides)
        with patch('nivon.conab_gcs_archive.preparar_lote',return_value=self.plano):
            return arquivar_lote(**args)

    def test_preflight_sem_rede_e_sem_upload(self):
        out=self._executar(executar=False)
        self.assertFalse(out['cloud_gravado'])
        self.assertEqual(self.bucket.objetos,{})

    def test_gates_sem_direitos_recusam_upload(self):
        with self.assertRaises(PermissionError):
            self._executar(direitos_armazenamento=False)
        self.assertEqual(self.bucket.objetos,{})

    def test_persiste_uma_edicao_com_readback_e_idempotencia(self):
        out=self._executar()
        self.assertEqual(out['status'],'RAW_CONAB_IMUTAVEL_GCS_COM_READBACK')
        self.assertTrue(out['cloud_gravado'])
        self.assertFalse(out['publicacao_permitida'])
        self.assertEqual(len(self.bucket.objetos),2)
        self.assertEqual(self.bucket.objetos[self.path+'/raw.xlsx'][0],self.raw.read_bytes())
        again=self._executar()
        self.assertTrue(again['cloud_gravado'])
        self.assertEqual(len(self.bucket.objetos),2)

    def test_objeto_corrompido_no_bucket_bloqueia_sucesso(self):
        self.bucket.corromper=True
        with self.assertRaises(ErroArquivoConabGCS):
            self._executar()

    def test_objeto_antigo_mesmo_path_digest_diferente_bloqueia(self):
        self.bucket.objetos[self.path+'/raw.xlsx']=(b'outro',
                                      {'sha256':'0'*64},'application/octet-stream')
        with self.assertRaises(ErroArquivoConabGCS):
            self._executar()

    def test_bucket_ou_prefixo_estranho_recusado(self):
        with self.assertRaises(ErroArquivoConabGCS):
            _guardar(self.bucket,'gs://other/nivon/conab/progresso/v1/a.xlsx',
                b'xyz',sha=sha256(b'xyz').hexdigest(),mime='application/octet-stream',
                metadata={},precondition_failed=JaExistente)

if __name__=='__main__':
    import unittest
    unittest.main()
