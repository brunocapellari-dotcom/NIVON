"""RAW GCS: integridade, imutabilidade e idempotência sem rede."""
import json
import tempfile
import unittest
from pathlib import Path
from datetime import datetime,timezone

from nivon.ingestao_fontes_reais import gravar_lote
from nivon.arquivo_raw_gcs import (
    preparar_manifesto,arquivar_gcs,ErroArquivoCloud
)


class Blob:
    def __init__(self,bucket,key):
        self.bucket=bucket
        self.key=key
        self.metadata=None
    def upload_from_filename(self,path,*,content_type,if_generation_match,checksum,timeout):
        assert if_generation_match==0 and checksum=="crc32c"
        self.bucket.existing[self.key]=(Path(path).read_bytes(),dict(self.metadata))


class Stored:
    def __init__(self,raw,metadata):
        self.raw=raw
        self.size=len(raw)
        self.metadata=metadata
    def download_to_filename(self,path):
        Path(path).write_bytes(self.raw)


class Bucket:
    def __init__(self):
        self.existing={}
    def blob(self,key):
        return Blob(self,key)
    def get_blob(self,key):
        tup=self.existing.get(key)
        return Stored(*tup) if tup else None


class Client:
    def __init__(self):
        self.value=Bucket()
    def bucket(self,name):
        assert name=="nivon-raw-archive"
        return self.value


class ArquivoRawTest(unittest.TestCase):
    def setUp(self):
        temp=tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root=Path(temp.name)
        self.db=self.root/"stage.sqlite"
        self.raw=self.root/"raw"
        self.payload=b'{"results":[{"value":1}]}'
        self.record=gravar_lote(
           banco=self.db,diretorio_bruto=self.raw,
           dataset_id="ARG_BCRA_V1",
           origem="https://api.bcra.gob.ar/estadisticas/v4.0/Monetarias/1",
           raw=self.payload,tipo="application/json",
           coletado_em=datetime(2026,10,23,tzinfo=timezone.utc),
           registros=[],estado="RAW_RECEIVED")

    def test_end_to_end_manifesto_gcs_idempotencia(self):
        manifest=preparar_manifesto(banco=self.db,raw_dir=self.raw,bucket="nivon-raw-archive")
        self.assertEqual(manifest["quantidade"],1)
        self.assertEqual(manifest["objetos"][0]["sha256"],self.record["sha256"])
        client=Client()
        with self.assertRaises(PermissionError):
            arquivar_gcs(banco=self.db,raw_dir=self.raw,bucket="nivon-raw-archive")
        a=arquivar_gcs(banco=self.db,raw_dir=self.raw,bucket="nivon-raw-archive",
                      client=client,executar=True)
        b=arquivar_gcs(banco=self.db,raw_dir=self.raw,bucket="nivon-raw-archive",
                      client=client,executar=True)
        self.assertEqual((a["novos"],b["ja_existiam"]),(1,1))
        self.assertEqual(len(client.value.existing),1)
        self.assertTrue(a["executado"])
        self.assertFalse(a["bigquery_executado"])

    def test_mesmo_tamanho_e_metadata_nao_mascaram_corrupcao(self):
        client=Client()
        arquivar_gcs(banco=self.db,raw_dir=self.raw,bucket="nivon-raw-archive",
                     client=client,executar=True)
        key=next(iter(client.value.existing))
        original,metadata=client.value.existing[key]
        client.value.existing[key]=(b"X"*len(original),metadata)
        with self.assertRaisesRegex(ErroArquivoCloud,"corrompido"):
            arquivar_gcs(banco=self.db,raw_dir=self.raw,bucket="nivon-raw-archive",
                         client=client,executar=True)

    def test_rejeitar_fraude_e_tampering(self):
        client=Client()
        m=preparar_manifesto(banco=self.db,raw_dir=self.raw,bucket="nivon-raw-archive")
        blob=m["objetos"][0]["objeto"]
        client.value.existing[blob]=(b"WRONG",{"sha256":self.record["sha256"]})
        with self.assertRaises(ErroArquivoCloud):
            arquivar_gcs(banco=self.db,raw_dir=self.raw,bucket="nivon-raw-archive",
                         client=client,executar=True)
        Path(self.record["arquivo_raw"]).write_bytes(b"MUTATED")
        with self.assertRaises(ErroArquivoCloud):
            preparar_manifesto(banco=self.db,raw_dir=self.raw,bucket="nivon-raw-archive")
        for bucket in ("http://localhost","GOOGLE_SECRET",".abc","not/valid","gg"):
            with self.subTest(bucket=bucket),self.assertRaises(ErroArquivoCloud):
                preparar_manifesto(banco=self.db,raw_dir=self.raw,bucket=bucket)

if __name__=="__main__":
    unittest.main()
