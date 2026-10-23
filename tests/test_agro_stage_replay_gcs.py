"""Replay de staging agro a partir de objeto GCS, com integridade e sem SQLite."""
from __future__ import annotations
import json
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

from nivon.ingestao_fontes_reais import gravar_lote
from nivon.agro_staging_bigquery import (
    reprocessar_stage_quarentena, exportar_quarentena, ErroStagingAgro,
    _sha,
)


class ObjetoGCS:
    def __init__(self,dados,meta):
        self.dados=dados
        self.size=len(dados)
        self.metadata=meta
    def download_to_filename(self,nome):
        Path(nome).write_bytes(self.dados)


class Armazem:
    def __init__(self):
        self.objs={}
    def get_blob(self,name):
        return self.objs.get(name)


class Storage:
    def __init__(self):
        self.b=Armazem()
        self.reads=0
    def bucket(self,name):
        self.reads+=1
        assert name=="nivon-data-raw-2026"
        return self.b


class ReplayE2E(unittest.TestCase):
    def setUp(self):
        temp=tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root=Path(temp.name)
        self.db=self.root/"lote.sqlite"
        self.raw=self.root/"raw"
        self.jsonl=self.root/"staging.jsonl"
        gravar_lote(
            banco=self.db,diretorio_bruto=self.raw,
            dataset_id="IMEA_PUBLICACOES_STAGING",
            origem="https://api1.imea.com.br/api/v2/mobile/cadeias/4/cotacoes",
            raw=b'{"indicador":"soja"}',tipo="application/json",
            coletado_em=datetime(2026,10,23,tzinfo=timezone.utc),
            estado="QUARANTINED",
            registros=[{"identidade":"preco-soja","referencia":"2026-10-22",
                        "publicacao":"2026-10-22T12:00:00-04:00",
                        "natureza":"INFORMADO","unidade":"R$/sc",
                        "valor":"150.0","campos":{"data_referencia":None,
                            "tipo_referencia":"PUBLICACAO_NAO_EQUIVALE_DATA_REFERENCIA"}}])
        exportar_quarentena(
            banco=self.db,destino=self.jsonl,
            fonte_dataset="IMEA_PUBLICACOES_STAGING")
        self.sha=_sha(self.jsonl)
        self.objeto=f"nivon/staging-agro-quarentena/v1/{self.sha}.jsonl"
        self.storage=Storage()
        self.storage.b.objs[self.objeto]=ObjetoGCS(
            self.jsonl.read_bytes(),{"sha256":self.sha})

    def opts(self):
        return dict(sha256=self.sha,fonte_dataset="IMEA_PUBLICACOES_STAGING",
                    bucket="nivon-data-raw-2026",project_id="nivon-data",
                    dataset_id="nivon_raw",storage_client=self.storage)

    def test_replay_offline_nao_toca_gcs(self):
        out=reprocessar_stage_quarentena(**self.opts(),executar=False)
        self.assertFalse(out["executado"])
        self.assertEqual(self.storage.reads,0)

    def test_replay_sem_sqlite_nem_raw_local(self):
        self.db.unlink()
        self.jsonl.unlink()
        self.assertFalse(self.db.exists())
        chamadas=[]
        def fake_carregar(**k):
            linhas=[json.loads(s) for s in Path(k["arquivo"]).read_text().splitlines()]
            self.assertTrue(k["executar"])
            self.assertIsNone(linhas[0]["data_referencia"])
            chamadas.append(linhas)
            return {"bigquery_executado":True,"linhas":len(linhas)}
        with patch("nivon.agro_staging_bigquery.carregar_stage",
                   side_effect=fake_carregar):
            out=reprocessar_stage_quarentena(**self.opts(),executar=True)
        self.assertTrue(out["executado"])
        self.assertFalse(out["sqlite_necessario"])
        self.assertFalse(out["promocao_canonica"])
        self.assertEqual(out["linhas"],1)
        self.assertEqual(len(chamadas),1)

    def test_objeto_adulterado_falha_antes_do_bigquery(self):
        self.storage.b.objs[self.objeto]=ObjetoGCS(
            b'X'*len(self.jsonl.read_bytes()),{"sha256":self.sha})
        with patch("nivon.agro_staging_bigquery.carregar_stage") as merge:
            with self.assertRaisesRegex(ErroStagingAgro,"adulterado"):
                reprocessar_stage_quarentena(**self.opts(),executar=True)
        merge.assert_not_called()

    def test_metadados_ou_destino_errado_recusado(self):
        self.storage.b.objs[self.objeto].metadata={"sha256":"0"*64}
        with self.assertRaises(ErroStagingAgro):
            reprocessar_stage_quarentena(**self.opts(),executar=True)
        with self.assertRaises(ErroStagingAgro):
            reprocessar_stage_quarentena(**{**self.opts(),
                "fonte_dataset":"CONAB_SAFRAS_STAGING"},executar=True)

    def test_nao_pode_reprocessar_no_canonico(self):
        with self.assertRaises(ErroStagingAgro):
            reprocessar_stage_quarentena(
                **{**self.opts(),"fonte_dataset":"CEPEA_PRECOS_FISICOS"},
                executar=True)

if __name__=="__main__":
    unittest.main()
