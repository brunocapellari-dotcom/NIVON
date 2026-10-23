"""Verificação ponta a ponta com clientes GCS/BigQuery simulados, sem rede."""
import json
import sys
import tempfile
import types
import unittest
from datetime import datetime,timezone
from pathlib import Path
from unittest.mock import patch

from nivon.ingestao_fontes_reais import gravar_lote, exportar_jsonl
from nivon.verificacao_cloud_fontes import (
    verificar_publicacao,ErroVerificacaoCloud,
)

class FakeObject:
    def __init__(self, raw, metadata, alterar=False):
        self.raw=raw
        self.size=len(raw)
        self.metadata=metadata
        self.alterar=alterar
    def download_as_bytes(self,timeout=None):
        if self.alterar:
            return b"alterado"
        return self.raw

class FakeBucket:
    def __init__(self, blob_map):
        self.blob_map=blob_map
    def get_blob(self, name):
        return self.blob_map.get(name)

class FakeStorage:
    def __init__(self, blobs):
        self.blobs=blobs
    def bucket(self, name):
        assert name=="nivon-raw-archive"
        return FakeBucket(self.blobs)

class FakeJob:
    def __init__(self, rows):
        self.rows=rows
    def result(self,timeout=90):
        return self.rows

class FakeBQ:
    def __init__(self, rows):
        self.rows=rows
        self.calls=[]
    def query(self, sql, job_config=None):
        assert "data_referencia BETWEEN @inicio AND @fim" in sql
        assert "UNNEST(@hashes)" in sql
        assert "nivon_observacoes" in sql
        assert job_config.maximum_bytes_billed==100_000_000
        self.calls.append(sql)
        return FakeJob(self.rows)

def fake_google():
    bigquery=types.ModuleType("google.cloud.bigquery")
    bigquery.QueryJobConfig=lambda **kw: types.SimpleNamespace(**kw)
    bigquery.ScalarQueryParameter=lambda name,kind,value: (name,kind,value)
    bigquery.ArrayQueryParameter=lambda name,kind,values: (name,kind,values)
    storage=types.ModuleType("google.cloud.storage")
    cloud=types.ModuleType("google.cloud")
    cloud.bigquery=bigquery
    cloud.storage=storage
    google=types.ModuleType("google")
    google.cloud=cloud
    return {"google":google,"google.cloud":cloud,
            "google.cloud.bigquery":bigquery,
            "google.cloud.storage":storage}

class VerifyCloudTest(unittest.TestCase):
    def setUp(self):
        tmp=tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root=Path(tmp.name)
        self.db=self.root/"dados.sqlite"
        self.raw=self.root/"raw"
        for i in (1,2):
            gravar_lote(
                banco=self.db,diretorio_bruto=self.raw,
                dataset_id="ARG_BCRA_V1",
                origem=f"https://api.bcra.gob.ar/estadisticas/v4.0/Monetarias/{i}",
                raw=json.dumps({"i":i}).encode(),tipo="application/json",
                coletado_em=datetime(2026,10,23,tzinfo=timezone.utc),
                registros=[{"identidade":f"REF_{i}","referencia":f"2026-10-0{i}",
                    "natureza":"INFORMADO","campos":{"v":i},"valor":i}],
                estado="NORMALIZED")
        self.jsonl=self.root/"staging.jsonl"
        exportar_jsonl(banco=self.db,destino=self.jsonl)
        from nivon.arquivo_raw_gcs import preparar_manifesto
        m=preparar_manifesto(banco=self.db,raw_dir=self.raw,bucket="nivon-raw-archive")
        self.blobs={r["objeto"]:FakeObject(
            Path(r["arquivo_local"]).read_bytes(),{
                "sha256":r["sha256"],"snapshot_id":r["snapshot_id"]})
            for r in m["objetos"]}
        self.rows=[]
        for line in self.jsonl.read_text().splitlines():
            row=json.loads(line)
            self.rows.append({"dataset_id":row["dataset_id"],
                "fingerprint":row["fingerprint"],"referencia":row["referencia"]})

    def call(self,*,rows=None,blobs=None,executar=True):
        args=dict(banco=self.db,raw_dir=self.raw,bucket="nivon-raw-archive",
            arquivo_jsonl=self.jsonl,project_id="nivon-data",dataset_id="agro",
            executar=executar,client_storage=FakeStorage(self.blobs if blobs is None else blobs),
            client_bq=FakeBQ(self.rows if rows is None else rows))
        with patch.dict(sys.modules,fake_google()):
            return verificar_publicacao(**args)

    def test_validar_ponta_a_ponta(self):
        resultado=self.call()
        self.assertTrue(resultado["executado"])
        self.assertEqual(resultado["objetos_gcs_confirmados"],2)
        self.assertEqual(resultado["amostras_bigquery_confirmadas"],2)
        self.assertEqual(resultado["linhas_jsonl"],2)
        self.assertFalse(resultado["dados_publicados_externamente"])

    def test_planejamento_nunca_usa_rede(self):
        resultado=self.call(executar=False)
        self.assertFalse(resultado["executado"])
        self.assertEqual(resultado["amostras_bigquery"],2)

    def test_falta_de_linha_no_bq_reprova(self):
        with self.assertRaises(ErroVerificacaoCloud):
            self.call(rows=self.rows[:1])

    def test_gcs_inexistente_ou_alterado_reprova(self):
        with self.assertRaises(ErroVerificacaoCloud):
            self.call(blobs={})
        corrupted=dict(self.blobs)
        key=sorted(corrupted)[0]
        original=corrupted[key]
        corrupted[key]=FakeObject(original.raw,original.metadata,alterar=True)
        with self.assertRaises(ErroVerificacaoCloud):
            self.call(blobs=corrupted)

if __name__=="__main__":
    unittest.main()
