"""E2E sintético: RAW GCS canônico + stage/manifests + replay sem runner."""
from __future__ import annotations

import json
import shutil
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

from nivon.arquivo_raw_gcs import arquivar_gcs, preparar_manifesto
from nivon.ingestao_fontes_reais import gravar_lote, exportar_jsonl
from nivon.lote_cloud_recuperavel import (
    ErroLoteCloud, preparar_lote, arquivar_stage, reprocessar_manifesto,
    _upload_imutavel,
)

DESTINO = {"bucket": "nivon-raw-archive", "projeto": "nivon-data", "dataset": "agro"}


class Blob:
    def __init__(self, bucket, key):
        self.bucket, self.key = bucket, key
        self.metadata = None

    def upload_from_filename(self, filename, *, content_type, if_generation_match,
                             checksum, timeout):
        assert if_generation_match == 0 and checksum == "crc32c"
        if self.key in self.bucket.objects:
            raise AssertionError("tentativa de sobrescrita")
        self.bucket.objects[self.key] = (
            Path(filename).read_bytes(), dict(self.metadata))

    def download_to_filename(self, filename):
        Path(filename).write_bytes(self.bucket.objects[self.key][0])


class Stored:
    def __init__(self, bucket, key):
        self.bucket, self.key = bucket, key
        raw, metadata = bucket.objects[key]
        self.size = len(raw)
        self.metadata = dict(metadata)

    def download_to_filename(self, filename):
        Path(filename).write_bytes(self.bucket.objects[self.key][0])


class Bucket:
    def __init__(self):
        self.objects = {}

    def get_blob(self, key):
        return Stored(self, key) if key in self.objects else None

    def blob(self, key):
        return Blob(self, key)


class Client:
    def __init__(self):
        self.storage = Bucket()

    def bucket(self, name):
        assert name == "nivon-raw-archive"
        return self.storage


class TestLoteCloudE2E(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        self.db = self.root / "dados.sqlite"
        self.raw = self.root / "raw"
        self.stage = self.root / "stage.jsonl"
        self.client = Client()
        self._gerar("ARG_BCRA_V1", "NORMALIZED")
        self._gerar("IMEA_WORKBOOK", "QUARANTINED")
        exportar_jsonl(banco=self.db, destino=self.stage, dataset_id="ARG_BCRA_V1")

    def _gerar(self, fonte, estado):
        return gravar_lote(
            banco=self.db, diretorio_bruto=self.raw,
            dataset_id=fonte, origem="https://api.dados-exemplo.org/data.json",
            raw=json.dumps({"fonte": fonte}).encode(),
            tipo="application/json", coletado_em=datetime(2026,10,23,tzinfo=timezone.utc),
            estado=estado,
            registros=[{"identidade":"item-1","referencia":"2026-10-22",
                        "natureza":"INFORMADO","campos":{"origem":fonte},
                        "valor":"123.00","competencia":"2026-10"}])

    def _arquivar_raw(self):
        return arquivar_gcs(
            banco=self.db, raw_dir=self.raw, bucket=DESTINO["bucket"],
            client=self.client, executar=True, fonte_dataset="ARG_BCRA_V1")

    def _stage_salvo(self):
        self._arquivar_raw()
        return arquivar_stage(
            banco=self.db, arquivo_jsonl=self.stage,
            client=self.client, executar=True, **DESTINO)

    def test_arquivo_raw_por_fonte_isola_quarentena(self):
        plano = preparar_manifesto(banco=self.db, raw_dir=self.raw,
                                   bucket=DESTINO["bucket"], fonte_dataset="ARG_BCRA_V1")
        self.assertEqual(plano["quantidade"], 1)
        self.assertEqual(plano["objetos"][0]["dataset"], "ARG_BCRA_V1")
        self._arquivar_raw()
        self.assertEqual(len(self.client.storage.objects), 1)

    def test_preflight_lote_nao_exige_nuvem(self):
        plano = preparar_lote(
            banco=self.db, arquivo_jsonl=self.stage, **DESTINO)
        self.assertEqual(plano["plano"]["linhas"],1)
        self.assertEqual(len(plano["plano"]["snapshots"]),1)
        planejamento=arquivar_stage(banco=self.db,arquivo_jsonl=self.stage,
                                    executar=False,**DESTINO)
        self.assertFalse(planejamento["executado"])
        self.assertFalse(self.client.storage.objects)

    def test_replay_e2e_sem_sqlite_e_sem_http(self):
        enviado = self._stage_salvo()
        self.assertEqual(enviado["linhas"], 1)
        self.assertFalse(enviado["bigquery_executado"])
        self.assertEqual(len(self.client.storage.objects),3)
        novamente=arquivar_stage(
            banco=self.db, arquivo_jsonl=self.stage, client=self.client,
            executar=True, **DESTINO)
        self.assertEqual(novamente["stage"],"EXISTENTE_CONFERIDO")
        sha = enviado["manifesto_sha256"]
        self.db.unlink()
        # RAW local nao participa da recuperacao.
        shutil.rmtree(self.raw)
        chamadas = []
        def carregar(**kwargs):
            rows=[json.loads(x) for x in Path(kwargs["arquivo"]).read_text().splitlines()]
            chamadas.extend(rows)
            return {"executado":True}
        result=reprocessar_manifesto(
            manifesto_sha256=sha,client=self.client,loader=carregar,
            executar=True,**DESTINO)
        self.assertEqual(result["linhas"],1)
        self.assertTrue(result["replay_sem_sqlite"])
        self.assertEqual(len(chamadas),1)
        self.assertEqual(chamadas[0]["dataset_id"],"ARG_BCRA_V1")

    def test_quarentena_falha_antes_de_cloud(self):
        exportar_jsonl(banco=self.db,destino=self.stage)
        with self.assertRaisesRegex(ErroLoteCloud,"quarentena"):
            preparar_lote(banco=self.db, arquivo_jsonl=self.stage,**DESTINO)
        self.assertFalse(self.client.storage.objects)

    def test_falha_se_raw_nao_esta_arquivado(self):
        with self.assertRaises(ErroLoteCloud):
            arquivar_stage(banco=self.db,arquivo_jsonl=self.stage,
                           client=self.client, executar=True,**DESTINO)
        self.assertFalse(self.client.storage.objects)

    def test_replay_nao_muda_destino_nem_aceita_stage_adulterado(self):
        enviado=self._stage_salvo()
        sha=enviado["manifesto_sha256"]
        with self.assertRaises(ErroLoteCloud):
            reprocessar_manifesto(
                manifesto_sha256=sha, client=self.client,
                loader=lambda **kw: {"executado":True},executar=True,
                bucket=DESTINO["bucket"],projeto=DESTINO["projeto"],
                dataset="outro_dataset")
        stage=next(x for x in self.client.storage.objects
                   if x.startswith("nivon/staging/"))
        original,meta=self.client.storage.objects[stage]
        self.client.storage.objects[stage]=(b"X" * len(original),meta)
        with self.assertRaises(ErroLoteCloud):
            reprocessar_manifesto(
                manifesto_sha256=sha,client=self.client,
                loader=lambda **kw: {"executado":True},
                executar=True,**DESTINO)

    def test_upload_rejeita_stage_alterado_apos_plano(self):
        arquivo=self.root/"race.jsonl"
        arquivo.write_bytes(b"original")
        with self.assertRaisesRegex(ErroLoteCloud,"alterado"):
            _upload_imutavel(
                self.client.storage,arquivo=arquivo,
                nome="nivon/staging/v1/"+"a"*64+".jsonl",
                sha="a"*64,mime="application/x-ndjson")
        self.assertFalse(self.client.storage.objects)

    def test_replay_sem_execucao_nao_consulta_cloud(self):
        r=reprocessar_manifesto(manifesto_sha256="a"*64,
                                executar=False,**DESTINO)
        self.assertFalse(r["executado"])

if __name__=="__main__":
    unittest.main()
