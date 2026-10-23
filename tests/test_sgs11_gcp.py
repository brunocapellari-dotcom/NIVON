"""E2E SGS11 com respostas oficiais sintéticas e ponte Cloud simulada."""
from __future__ import annotations

import json
import sqlite3
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

from nivon.sgs11_gcp import (
    DATASET, URL, OPERACOES, ErroSGSCloud,
    coletar_http, normalizar, executar_lote, main,
)
from nivon.ingestao_fontes_reais import exportar_jsonl

NOW=datetime(2026,10,23,18,tzinfo=timezone.utc)
JSON_OFICIAL=b'[{"data":"22/10/2026","valor":"0,055"}]'


class Resposta:
    def __init__(self,raw=JSON_OFICIAL, status=200, url=URL,
                 mime="application/json"):
        self.raw=raw
        self.status=status
        self.url=url
        self.headers={"Content-Type":mime}
    def geturl(self):return self.url
    def read(self,n):return self.raw[:n]
    def __enter__(self):return self
    def __exit__(self,*exc):return False

class Abridor:
    def __init__(self,**kwargs):
        self.response=Resposta(**kwargs)
        self.calls=0
    def open(self,request,timeout):
        self.calls+=1
        assert request.full_url==URL
        return self.response


class TestSGS11GoogleCloud(unittest.TestCase):
    def test_parser_bcb_dado_diario_serie11(self):
        out=normalizar(JSON_OFICIAL,coletado_em=NOW)
        self.assertEqual(len(out),1)
        r=out[0]
        self.assertEqual(r["valor"],"0.055")
        self.assertEqual(r["referencia"],"2026-10-22")
        self.assertEqual(r["competencia"],"2026-10")
        self.assertEqual(r["unidade"],"PERCENTUAL_AO_DIA")
        self.assertEqual(r["natureza"],"INFORMADO")
        self.assertIsNone(r["publicacao"])
        self.assertTrue(r["campos"]["nao_equivale_a_meta_selic_anual"])

    def test_http_respostas_inadequadas_sao_bloqueadas(self):
        for caso in [
            dict(raw=b"<html>Request Rejected</html>"),
            dict(status=302),
            dict(url="https://site-indevido.example/"),
            dict(mime="text/html"),
            dict(raw=b""),
            dict(raw=b"a" * 250001),
        ]:
            with self.subTest(caso=sorted(caso)),self.assertRaises(ErroSGSCloud):
                coletar_http(abridor=Abridor(**caso))

    def test_parser_failclosed_futuro_duplicado_ausente(self):
        for raw in [
            b"[]",
            b"not a json",
            b'[{"data":"24/10/2026","valor":"0,050"}]',
            b'[{"data":"22/10/2026","valor":"-1"}]',
            b'[{"data":"22/10/2026","valor":"NaN"}]',
            b'[{"data":"22/10/2026","valor":"0,05","valor":"0,06"}]',
            b'[{"data":"22/10/2026","valor":"0,05"},{"data":"22/10/2026","valor":"0,06"}]',
        ]:
            with self.subTest(raw=raw),self.assertRaises(ErroSGSCloud):
                normalizar(raw,coletado_em=NOW)

    def test_preflight_acontece_antes_http(self):
        http=Abridor()
        with tempfile.TemporaryDirectory() as root:
            with self.assertRaises(PermissionError):
                executar_lote(base=root,projeto="nivon-data",dataset="nivon_raw",
                    bucket="nivon-data-raw-2026",executar=False,abridor=http)
            self.assertEqual(http.calls,0)
            with self.assertRaises(ErroSGSCloud):
                executar_lote(base=root,projeto="nivon-data",dataset="nivon_raw",
                    bucket="nivon-data-raw-2026",executar=True,autorizacoes=OPERACOES,
                    evidencia="Uso interno de dados públicos validado",
                    abridor=http,
                    preflight=lambda **kw: {"bucket_existe":False,"tabela_validada":False})
            self.assertEqual(http.calls,0)

    def test_e2e_raw_gcs_stage_merge_e_leitura(self):
        with tempfile.TemporaryDirectory() as root:
            base=Path(root)
            hist=[]
            def preflight(**kw):
                hist.append("PREFLIGHT")
                self.assertEqual(kw["projeto"],"nivon-data")
                return {"bucket_existe":True,"tabela_validada":True}
            def raw_upload(**kw):
                hist.append("GCS_RAW")
                self.assertEqual(kw["fonte_dataset"],DATASET)
                self.assertTrue(Path(kw["banco"]).is_file())
                self.assertEqual(len(kw["snapshot_ids"]),1)
                return {"executado":True}
            def stage_upload(**kw):
                hist.append("STAGE_RECUPERAVEL")
                rows=[json.loads(s) for s in kw["arquivo_jsonl"].read_text().splitlines()]
                self.assertEqual(len(rows),1)
                self.assertEqual(rows[0]["dataset_id"],DATASET)
                self.assertEqual(rows[0]["referencia"],"2026-10-22")
                self.assertEqual(rows[0]["natureza"],"INFORMADO")
                self.assertIsNone(rows[0]["publicacao"])
                return {"executado":True,"manifesto_sha256":"a"*64}
            def bq_load(**kw):
                hist.append("BQ_MERGE")
                self.assertTrue(kw["executar"])
                return {"executado":True}
            def verificar(**kw):
                hist.append("READBACK")
                self.assertTrue(kw["executar"])
                return {"executado":True,"amostras_bigquery_confirmadas":1}
            params=dict(
                base=base,projeto="nivon-data",dataset="nivon_raw",
                bucket="nivon-data-raw-2026",executar=True,
                autorizacoes=OPERACOES,evidencia="Fonte BCB pública com permissão de coleta",
                agora=NOW,abridor=Abridor(),preflight=preflight,
                raw_upload=raw_upload,stage_upload=stage_upload,
                bq_load=bq_load,verificacao=verificar)
            out=executar_lote(**params)
            self.assertEqual(hist,["PREFLIGHT","GCS_RAW","STAGE_RECUPERAVEL",
                                   "BQ_MERGE","READBACK"])
            self.assertEqual(out["status"],"GCS_BIGQUERY_CONFERIDOS")
            self.assertEqual(out["novas_observacoes_locais"],1)
            self.assertEqual(out["bigquery_amostras_conferidas"],1)
            self.assertFalse(out["publicacao_externa"])
            with sqlite3.connect(base/"fontes_reais.sqlite") as db:
                state=db.execute("SELECT estado FROM snapshots").fetchone()[0]
                n=db.execute("SELECT count(*) FROM observacoes").fetchone()[0]
            self.assertEqual((state,n),("NORMALIZED",1))
            hist.clear()
            novamente=executar_lote(**params)
            self.assertEqual(novamente["novas_observacoes_locais"],0)
            self.assertEqual(hist,["PREFLIGHT","GCS_RAW","STAGE_RECUPERAVEL",
                                   "BQ_MERGE","READBACK"])

    def test_nao_declara_sucesso_se_bigquery_ou_readback_falha(self):
        with tempfile.TemporaryDirectory() as root:
            args=dict(base=root,projeto="nivon-data",dataset="nivon_raw",
                bucket="nivon-data-raw-2026",executar=True,
                autorizacoes=OPERACOES,evidencia="Uso de dados SGS BCB autorizado",
                agora=NOW,abridor=Abridor(),
                preflight=lambda **kw: {"tabela_validada":True,"bucket_existe":True},
                raw_upload=lambda **kw: {"executado":True},
                stage_upload=lambda **kw: {"executado":True,"manifesto_sha256":"b"*64})
            with self.assertRaisesRegex(ErroSGSCloud,"MERGE"):
                executar_lote(**args,bq_load=lambda **kw: {"executado":False})
            with self.assertRaisesRegex(ErroSGSCloud,"pós-carga"):
                executar_lote(**args,bq_load=lambda **kw: {"executado":True},
                    verificacao=lambda **kw: {"executado":True,
                                             "amostras_bigquery_confirmadas":0})

    def test_cli_inerte_por_padrao(self):
        import io
        from contextlib import redirect_stdout
        stream=io.StringIO()
        with redirect_stdout(stream):
            result=main([])
        self.assertEqual(result,0)
        p=json.loads(stream.getvalue())
        self.assertEqual(p["status"],"PLANO_SEM_REDE")
        self.assertFalse(p["cloud_executado"])


if __name__=="__main__":
    unittest.main()
