"""GCS RAW + BigQuery MERGE integration with fake clients and synthetic sources."""
import json
import sqlite3
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

from nivon.ingestao_fontes_reais import gravar_lote
from nivon.persistencia_google_cloud import (
    ErroGoogleCloud, executar_envio, planejar_envio,
)


class FakeBlob:
    def __init__(self, name):
        self.name=name
        self.metadata=None
        self.size=0
        self.uploads=0

    def exists(self):
        return self.uploads>0

    def reload(self):
        return None

    def upload_from_filename(self, path, content_type=None, if_generation_match=None, timeout=None):
        if if_generation_match!=0:
            raise AssertionError("GCS overwrite is forbidden")
        if self.uploads:
            raise AssertionError("attempt to overwrite GCS")
        self.uploads+=1
        self.size=Path(path).stat().st_size


class FakeBucket:
    def __init__(self):
        self.files={}
    def exists(self):
        return True
    def blob(self, name):
        if name not in self.files:
            self.files[name]=FakeBlob(name)
        return self.files[name]


class FakeStorage:
    def __init__(self):
        self.obj=FakeBucket()
    def bucket(self, name):
        if name!="nivon-raw-exemplo-123":
            raise AssertionError(name)
        return self.obj


def montar(base, *,estado="NORMALIZED",dataset="BCB_PTAX"):
    base=Path(base)
    raw=b'{"value":[{"cotacaoVenda":5.3}]}'
    return gravar_lote(
        banco=base/"fontes_reais.sqlite",diretorio_bruto=base/"raw",
        dataset_id=dataset,
        origem="https://olinda.bcb.gov.br/example",
        raw=raw,tipo="application/json",
        coletado_em="2026-10-23T15:00:00Z",
        estado=estado,
        registros=[{
            "identidade":"USD|2026-10-23T12:00:00Z|FECHAMENTO",
            "referencia":"2026-10-23","competencia":"2026-10",
            "publicacao":None,"natureza":"INFORMADO","valor":5.3,
            "unidade":"BRL/USD","campos":{"valor":5.3,"fonte":"BCB_PTAX"},
        }],
    )


class TestPersistenciaGoogleCloud(unittest.TestCase):
    def kwargs(self,base):
        return dict(base=base,bucket="nivon-raw-exemplo-123",
                    project_id="nivon-data",dataset_id="nivon_stage")

    def direitos(self):
        return dict(executar=True,
            autorizacoes=frozenset({"COLETA","ARMAZENAMENTO","PROCESSAMENTO"}),
            evidencia="Autoriza dados publicos para uso interno 2026-10-23")

    def test_gcs_raw_e_jsonl_antes_bigquery_e_replay(self):
        with tempfile.TemporaryDirectory() as d:
            snapshot=montar(d)
            storage=FakeStorage()
            events=[]
            def bq_loader(**kwargs):
                # A GCS receipt must already exist before BQ starts.
                self.assertEqual(len(storage.obj.files),3)
                self.assertTrue(all(b.uploads==1 for b in storage.obj.files.values()))
                self.assertTrue(kwargs["executar"])
                events.append("BQ")
                return {"executado":True,"linhas":1}
            p=planejar_envio(**self.kwargs(d))
            self.assertEqual(p["estado"],"PREFLIGHT_OK")
            self.assertEqual(len(p["raw"]),1)
            self.assertEqual(p["bigquery"]["linhas"],1)
            run=executar_envio(**self.kwargs(d),**self.direitos(),
                               storage_client=storage,bq_loader=bq_loader)
            self.assertEqual(run["estado"],"GCS_E_BIGQUERY")
            self.assertTrue(run["bq_executado"])
            self.assertEqual(events,["BQ"])
            self.assertTrue(any(v.startswith("nivon/raw/BCB_PTAX/") for v in storage.obj.files))
            self.assertTrue(any(v.startswith("nivon/staging/") for v in storage.obj.files))
            self.assertTrue(any(v.startswith("nivon/manifests/") for v in storage.obj.files))
            self.assertEqual(run["raw_enviados"][0]["snapshot_id"],snapshot["snapshot_id"])
            again=executar_envio(**self.kwargs(d),**self.direitos(),
                                 storage_client=storage,bq_loader=bq_loader)
            self.assertEqual(again["raw_enviados"][0]["estado"],"EXISTENTE_CONFERIDO")
            self.assertTrue(all(f.uploads==1 for f in storage.obj.files.values()))
            self.assertEqual(events,["BQ","BQ"]) # idempotence delegated to MERGE

    def test_sem_direitos_bloqueia_antes_da_nuvem(self):
        with tempfile.TemporaryDirectory() as d:
            montar(d)
            storage=FakeStorage()
            with self.assertRaises(PermissionError):
                executar_envio(**self.kwargs(d),storage_client=storage,executar=True)
            self.assertFalse(storage.obj.files)

    def test_quarentena_enviavel_somente_raw_gcs_sem_bigquery(self):
        with tempfile.TemporaryDirectory() as d:
            montar(d,estado="QUARANTINED",dataset="IMEA_WORKBOOK_LEGADO_STAGING")
            with self.assertRaises(ErroGoogleCloud):
                planejar_envio(**self.kwargs(d),bigquery=True)
            cloud=executar_envio(**self.kwargs(d),bigquery=False,
                  **self.direitos(),storage_client=FakeStorage())
            self.assertEqual(cloud["estado"],"GCS_RAW_APENAS")
            self.assertFalse(cloud["bq_executado"])
            self.assertEqual(len(cloud["raw_enviados"]),1)

    def test_raw_adulterado_detectado_antes_upload(self):
        with tempfile.TemporaryDirectory() as d:
            result=montar(d)
            Path(result["arquivo_raw"]).write_bytes(b'{"foo":"bar"}')
            with self.assertRaises(ErroGoogleCloud):
                planejar_envio(**self.kwargs(d))

    def test_snapshot_inconsistente_rejeitado(self):
        with tempfile.TemporaryDirectory() as d:
            montar(d)
            with sqlite3.connect(Path(d)/"fontes_reais.sqlite") as db:
                db.execute("UPDATE snapshots SET snapshot_id=?",("b"*64,))
            with self.assertRaises(ErroGoogleCloud):
                planejar_envio(**self.kwargs(d))

    def test_reprova_gcs_objeto_existente_divergente(self):
        with tempfile.TemporaryDirectory() as d:
            montar(d)
            storage=FakeStorage()
            path=planejar_envio(**self.kwargs(d))["raw"][0]["objeto"]
            fake=storage.obj.blob(path)
            fake.uploads=1
            fake.size=3
            fake.metadata={"sha256":"a"*64}
            with self.assertRaises(ErroGoogleCloud):
                executar_envio(**self.kwargs(d),**self.direitos(),
                               storage_client=storage,bq_loader=lambda **kw: {"executado":True})

    def test_bigquery_sem_confirmacao_falha(self):
        with tempfile.TemporaryDirectory() as d:
            montar(d)
            with self.assertRaises(ErroGoogleCloud):
                executar_envio(**self.kwargs(d),**self.direitos(),
                               storage_client=FakeStorage(),
                               bq_loader=lambda **kw: {"executado":False})


if __name__=="__main__":
    unittest.main()
