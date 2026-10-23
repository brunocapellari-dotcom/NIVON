"""E2E: isolamento multi-fonte e replay GCS->BigQuery sem SQLite local."""
from __future__ import annotations

import json
import shutil
import tempfile
import unittest
from pathlib import Path

from nivon.ingestao_fontes_reais import gravar_lote
from nivon.persistencia_google_cloud import (
    ErroGoogleCloud, executar_envio, planejar_envio,
    reprocessar_bigquery_do_manifesto,
)

OPS = frozenset({"COLETA", "ARMAZENAMENTO", "PROCESSAMENTO"})
DESTINO = dict(bucket="nivon-raw-test-2026", project_id="nivon-data",
               dataset_id="nivon_staging")
PERMISSOES = dict(executar=True, autorizacoes=OPS,
                  evidencia="Permissao documentada para fixture sintética")


class Blob:
    def __init__(self):
        self.metadata = {}
        self.size = 0
        self.content = None
        self.uploads = 0

    def exists(self):
        return self.content is not None

    def reload(self):
        pass

    def upload_from_filename(self, path, content_type=None,
                             if_generation_match=None, timeout=None):
        if if_generation_match != 0 or self.content is not None:
            raise AssertionError("sobrescrita de RAW proibida")
        self.content = Path(path).read_bytes()
        self.size = len(self.content)
        self.uploads += 1

    def download_to_filename(self, path):
        if self.content is None:
            raise FileNotFoundError(path)
        Path(path).write_bytes(self.content)


class Bucket:
    def __init__(self):
        self.files = {}

    def exists(self):
        return True

    def blob(self, name):
        return self.files.setdefault(name, Blob())


class Storage:
    def __init__(self):
        self.obj = Bucket()

    def bucket(self, name):
        assert name == DESTINO["bucket"]
        return self.obj


def gerar(base, dataset, estado):
    return gravar_lote(
        banco=base / "fontes_reais.sqlite",
        diretorio_bruto=base / "raw",
        dataset_id=dataset,
        origem="https://dados.example.org/observacoes.json",
        raw=(f'{{"dataset":"{dataset}"}}').encode(),
        tipo="application/json",
        coletado_em="2026-10-23T13:00:00Z",
        estado=estado,
        registros=[dict(
            identidade="ITEM-001", referencia="2026-10-22",
            competencia="2026-10", publicacao=None,
            natureza="INFORMADO", unidade="t", valor=30,
            campos={"indicador": dataset, "valor": 30},
        )],
    )


class TestIsolamentoEReplay(unittest.TestCase):
    def test_isolamento_impede_quarentena_de_bloquear_fonte_aprovada(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            gerar(base, "BCB_PTAX", "NORMALIZED")
            gerar(base, "IMEA_WORKBOOK_LEGADO_STAGING", "QUARANTINED")
            with self.assertRaises(ErroGoogleCloud):
                planejar_envio(base=base, **DESTINO)
            plano = planejar_envio(base=base, fonte_dataset="BCB_PTAX", **DESTINO)
            self.assertEqual([x["dataset_id"] for x in plano["raw"]], ["BCB_PTAX"])
            self.assertEqual(plano["bigquery"]["linhas"], 1)
            self.assertIn("BCB_PTAX", plano["bigquery"]["arquivo"])
            storage = Storage()
            linhas = []
            def loader(**kwargs):
                linhas.extend(json.loads(row) for row in
                              Path(kwargs["arquivo"]).read_text().splitlines())
                return {"executado": True}
            resposta = executar_envio(base=base, fonte_dataset="BCB_PTAX",
                                      storage_client=storage, bq_loader=loader,
                                      **DESTINO, **PERMISSOES)
            self.assertEqual(resposta["estado"], "GCS_E_BIGQUERY")
            self.assertEqual(len(linhas), 1)
            self.assertEqual(linhas[0]["dataset_id"], "BCB_PTAX")
            self.assertFalse(any("/IMEA_" in x for x in storage.obj.files))

    def test_recupera_apos_falha_bigquery_sem_sqlite(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp) / "transitorio"
            gerar(base, "BCB_PTAX", "NORMALIZED")
            storage = Storage()
            with self.assertRaises(ErroGoogleCloud):
                executar_envio(base=base, fonte_dataset="BCB_PTAX",
                               storage_client=storage,
                               bq_loader=lambda **kw: {"executado": False},
                               **DESTINO, **PERMISSOES)
            manifestos = [key for key in storage.obj.files
                          if key.startswith("nivon/manifests/")]
            self.assertEqual(len(manifestos), 1)
            manifesto_sha = manifestos[0].split("/")[-1].removesuffix(".json")
            documento = json.loads(storage.obj.files[manifestos[0]].content)
            self.assertEqual(documento["carga_bigquery"]["linhas"], 1)
            self.assertEqual(documento["carga_bigquery"]["project_id"], "nivon-data")
            shutil.rmtree(base)
            chamados = []
            def bq_loader(**kw):
                chamados.extend(json.loads(x) for x in
                                Path(kw["arquivo"]).read_text().splitlines())
                return {"executado": True}
            argumentos = dict(DESTINO)
            argumentos.pop("bucket")
            resultado = reprocessar_bigquery_do_manifesto(
                bucket=DESTINO["bucket"], manifesto_sha256=manifesto_sha,
                storage_client=storage, bq_loader=bq_loader,
                **argumentos, **PERMISSOES)
            self.assertEqual(resultado["estado"], "BIGQUERY_RECUPERADO")
            self.assertEqual(len(chamados), 1)
            self.assertEqual(chamados[0]["dataset_id"], "BCB_PTAX")
            self.assertEqual(sum(b.uploads for b in storage.obj.files.values()), 3)

    def test_replay_rejeita_stage_adulterado_ou_destino_trocado(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            gerar(base, "BCB_PTAX", "NORMALIZED")
            storage = Storage()
            executar_envio(base=base, fonte_dataset="BCB_PTAX",
                           storage_client=storage,
                           bq_loader=lambda **kw: {"executado": True},
                           **DESTINO, **PERMISSOES)
            manifest = next(key for key in storage.obj.files
                            if key.startswith("nivon/manifests/"))
            sha = manifest.rsplit("/", 1)[1][:-5]
            with self.assertRaises(ErroGoogleCloud):
                reprocessar_bigquery_do_manifesto(
                    bucket=DESTINO["bucket"], manifesto_sha256=sha,
                    project_id="projeto-errado", dataset_id="nivon_staging",
                    storage_client=storage, bq_loader=lambda **kw: {"executado": True},
                    **PERMISSOES)
            stage = next(key for key in storage.obj.files
                         if key.startswith("nivon/staging/"))
            storage.obj.files[stage].content = b'{"fraude":true}\n'
            storage.obj.files[stage].size = len(storage.obj.files[stage].content)
            with self.assertRaises(ErroGoogleCloud):
                reprocessar_bigquery_do_manifesto(
                    manifesto_sha256=sha,
                    storage_client=storage, bq_loader=lambda **kw: {"executado": True},
                    **DESTINO, **PERMISSOES)

    def test_quarentena_sem_stage_nao_pode_ser_reprocessada(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            gerar(base, "IMEA_WORKBOOK_LEGADO_STAGING", "QUARANTINED")
            storage = Storage()
            executar_envio(base=base, fonte_dataset="IMEA_WORKBOOK_LEGADO_STAGING",
                           bigquery=False, storage_client=storage,
                           **DESTINO, **PERMISSOES)
            manifest = next(key for key in storage.obj.files
                            if key.startswith("nivon/manifests/"))
            sha = manifest.rsplit("/", 1)[1][:-5]
            with self.assertRaises(ErroGoogleCloud):
                reprocessar_bigquery_do_manifesto(
                    manifesto_sha256=sha, storage_client=storage,
                    bq_loader=lambda **kw: {"executado": True},
                    **DESTINO, **PERMISSOES)

    def test_permissoes_replay_falham_antes_da_rede(self):
        with self.assertRaises(PermissionError):
            reprocessar_bigquery_do_manifesto(
                bucket=DESTINO["bucket"], manifesto_sha256="a"*64,
                project_id=DESTINO["project_id"], dataset_id=DESTINO["dataset_id"],
                executar=False, autorizacoes=OPS)


if __name__ == "__main__":
    unittest.main()
