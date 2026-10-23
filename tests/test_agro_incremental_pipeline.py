"""Regressão: lotes pequenos, >=200 snapshots históricos e RAW sem delta."""
from __future__ import annotations

import hashlib
import os
import sqlite3
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

from nivon.ingestao_fontes_reais import gravar_lote,exportar_jsonl
from nivon.arquivo_raw_gcs import preparar_manifesto,ErroArquivoCloud
from nivon.agro_staging_bigquery import exportar_quarentena
from scripts.coletar_agro_google_cloud import executar_lote

NOW=datetime(2026,10,23,tzinfo=timezone.utc)


class TestLotesIncrementais(unittest.TestCase):
    def setUp(self):
        t=tempfile.TemporaryDirectory()
        self.addCleanup(t.cleanup)
        self.root=Path(t.name)
        self.db=self.root/"fontes_reais.sqlite"
        self.raw=self.root/"raw"

    def _registrar(self,ds,raw,identidade,estado="QUARANTINED",reg=None):
        return gravar_lote(
            banco=self.db,diretorio_bruto=self.raw,dataset_id=ds,
            origem="https://dados.example.org/data.json",
            raw=raw,tipo="application/json",coletado_em=NOW,
            estado=estado,registros=[reg or {
                "identidade":identidade,
                "referencia":"2026-10-22","publicacao":"2026-10-22T10:00:00Z",
                "natureza":"INFORMADO","campos":{
                    "data_referencia":None,
                    "tipo_referencia":"PUBLICACAO_NAO_EQUIVALE_DATA_REFERENCIA",
                    "indicador":identidade}}])

    def test_arquivar_apenas_snapshot_em_ledger_com_mais_de_200(self):
        ds="IMEA_PUBLICACOES_STAGING"
        alvo=self._registrar(ds,b'{"item":1}',"A")
        with sqlite3.connect(self.db) as db:
            for i in range(201):
                sha=hashlib.sha256(("hist-"+str(i)).encode()).hexdigest()
                sid=hashlib.sha256((ds+"|"+sha).encode()).hexdigest()
                db.execute("""INSERT OR IGNORE INTO snapshots
                    (snapshot_id,dataset_id,url_publica,sha256,coletado_em,
                     content_type,tamanho,arquivo,estado)
                    VALUES (?,?,?,?,?,?,?,?,?)""",(
                    sid,ds,"https://dados.example.org/legacy",sha,
                    "2026-10-20T00:00:00+00:00","application/json",10,
                    "/nao/existe/"+sha+".raw","QUARANTINED"))
        with self.assertRaises(ErroArquivoCloud):
            preparar_manifesto(banco=self.db,raw_dir=self.raw,
                               bucket="nivon-raw-archive",fonte_dataset=ds)
        plan=preparar_manifesto(
            banco=self.db,raw_dir=self.raw,bucket="nivon-raw-archive",
            fonte_dataset=ds,snapshot_ids=[alvo["snapshot_id"]])
        self.assertEqual(plan["quantidade"],1)
        self.assertEqual(plan["objetos"][0]["sha256"],alvo["sha256"])

    def test_jsonl_canonico_e_quarentena_filtrados_por_snapshot(self):
        ds="IMEA_PUBLICACOES_STAGING"
        a=self._registrar(ds,b'{"v":1}',"A")
        b=self._registrar(ds,b'{"v":2}',"B")
        out=exportar_quarentena(
            banco=self.db,destino=self.root/"stage.jsonl",
            fonte_dataset=ds,snapshot_ids=[b["snapshot_id"]])
        self.assertEqual(out["quantidade"],1)
        self.assertEqual(out["fonte_dataset"],ds)
        canonico="CEPEA_PRECOS_FISICOS"
        ca=self._registrar(canonico,b'{"a":1}',"IND-1",estado="NORMALIZED")
        cb=self._registrar(canonico,b'{"a":2}',"IND-2",estado="NORMALIZED")
        export=exportar_jsonl(
            banco=self.db,destino=self.root/"can.jsonl",dataset_id=canonico,
            snapshot_ids=[cb["snapshot_id"]])
        self.assertEqual(export["observacoes"],1)

    def test_raw_novo_sem_delta_nao_dispara_stage_bigquery(self):
        ds="IMEA_PUBLICACOES_STAGING"
        original={
            "identidade":"indicador_1","referencia":"2026-10-22",
            "natureza":"INFORMADO",
            "campos":{"data_referencia":None,
                      "tipo_referencia":"PUBLICACAO_NAO_EQUIVALE_DATA_REFERENCIA"}}
        self._registrar(ds,b'{"old":1}',"Z",reg=original)
        atual=self._registrar(ds,b'{"new":1}',"Z",reg=original)
        self.assertEqual(atual["novas_observacoes"],0)
        mocked={"dataset":ds,"estado":"QUARANTINED",
                "cadeias":[{"snapshot_id":atual["snapshot_id"]}],
                "novos":0}
        env={"NIVON_AGRO_FONTE_AUTORIZADA":"true",
             "NIVON_RAW_ARCHIVE_APPROVED":"true",
             "NIVON_ZERO_COST_BQ_APPROVED":"true"}
        with (patch.dict(os.environ,env,clear=True),
              patch("scripts.coletar_agro_google_cloud.coletar",return_value=mocked),
              patch("scripts.coletar_agro_google_cloud.arquivar_gcs",
                    return_value={"executado":True,"novos":1}) as arquivar):
            r=executar_lote(
                fonte="IMEA",base=self.root,executar=True,enviar_gcs=True,
                projeto="nivon-data",dataset="nivon_raw",
                bucket="nivon-raw-archive")
        self.assertEqual(r["estado"],"GCS_RAW_SEM_DELTA_ANALITICO")
        self.assertFalse(r["bigquery_executado"])
        self.assertEqual(arquivar.call_args.kwargs["snapshot_ids"],
                         [atual["snapshot_id"]])

if __name__=="__main__":
    unittest.main()
