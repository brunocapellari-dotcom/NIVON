"""Testes de contrato entre stage SQLite e JSONL BigQuery, SEM nuvem."""
import hashlib
import json
import os
import tempfile
import unittest
from pathlib import Path
from nivon.faostat_qcl_stream import gravar_snapshot_sqlite
from nivon.faostat_qcl_bigquery_export import ErroExportacaoQCL, exportar_stage_jsonl


def snapshot(valor="123.45",hash_="a"*64):
    return {
        "dataset_id":"FAO_FAOSTAT_LONG_RUN",
        "estado":"QCL_FILTRADO_SEM_PUBLICACAO",
        "sha256_zip":hash_,
        "data_coleta":"2026-10-21T23:00:00+00:00",
        "observacoes":[{
            "dataset_id":"FAO_FAOSTAT_LONG_RUN","source_id":"FAO","dominio":"QCL",
            "pais":"BRA","cultura":"SOJA","area_code":"21",
            "item_code":"236","element_code":"5510","ano":2023,
            "data_referencia":"2023","competencia":"2023","data_publicacao":None,
            "data_coleta":"2026-10-21T23:00:00+00:00",
            "valor":valor,"unidade":"t","flag_fonte":"A",
            "source_sha256":hash_,"data_atualizacao_fonte":"2025-12-31T00:00:00",
        }],
    }


class TestExportarQCL(unittest.TestCase):
    def test_sqlite_jsonl_explicito_sem_bigquery(self):
        with tempfile.TemporaryDirectory() as tmp:
            db=os.path.join(tmp,"qcl.db")
            path=os.path.join(tmp,"load.jsonl")
            self.assertEqual(gravar_snapshot_sqlite(snapshot(),arquivo_banco=db)["inseridas"],1)
            out=exportar_stage_jsonl(banco_sqlite=db,saida_jsonl=path)
            self.assertEqual(out["linhas"],1)
            self.assertFalse(out["bigquery_upload_executado"])
            self.assertFalse(out["cloud_resources_criados"])
            b=Path(path).read_bytes()
            self.assertEqual(out["sha256_jsonl"],hashlib.sha256(b).hexdigest())
            row=json.loads(b)
            self.assertEqual(row["data_referencia"],"2023-12-31")
            self.assertEqual(row["valor"],"123.45")
            self.assertEqual(row["source_id"],"FAO")
            self.assertIsNone(row["data_publicacao"])
            self.assertEqual(len(row["source_sha256"]),64)
            out2=exportar_stage_jsonl(banco_sqlite=db,saida_jsonl=path)
            self.assertEqual(out["sha256_jsonl"],out2["sha256_jsonl"])

    def test_revisao_preservada_com_sha_distinto(self):
        with tempfile.TemporaryDirectory() as tmp:
            db=os.path.join(tmp,"qcl.db")
            jsonl=os.path.join(tmp,"batch.jsonl")
            gravar_snapshot_sqlite(snapshot(),arquivo_banco=db)
            gravar_snapshot_sqlite(snapshot("135.0","b"*64),arquivo_banco=db)
            result=exportar_stage_jsonl(banco_sqlite=db,saida_jsonl=jsonl)
            self.assertEqual(result["linhas"],2)
            rows=[json.loads(x) for x in Path(jsonl).read_text().splitlines()]
            self.assertEqual({v["valor"] for v in rows},{"123.45","135.0"})

    def test_lote_excessivo_falha_sem_arquivo_parcial(self):
        with tempfile.TemporaryDirectory() as tmp:
            db=os.path.join(tmp,"qcl.db")
            jsonl=os.path.join(tmp,"batch.jsonl")
            gravar_snapshot_sqlite(snapshot(),arquivo_banco=db)
            gravar_snapshot_sqlite(snapshot("135.0","b"*64),arquivo_banco=db)
            with self.assertRaises(ErroExportacaoQCL):
                exportar_stage_jsonl(banco_sqlite=db,saida_jsonl=jsonl,max_linhas=1)
            self.assertFalse(Path(jsonl).exists())

    def test_contrato_bigquery_nao_cria_dataset(self):
        root=Path(__file__).resolve().parents[1]
        sql=(root/"sql"/"bigquery"/"001_faostat_qcl_snapshots.sql").read_text()
        self.assertIn("PARTITION BY data_referencia",sql)
        self.assertIn("CLUSTER BY pais, cultura",sql)
        self.assertIn("PROJECT_ID",sql)
        self.assertIn("DATASET_ID",sql)
        self.assertIn("data_publicacao TIMESTAMP",sql)
        self.assertNotIn("CREATE SCHEMA",sql)


if __name__=="__main__":
    unittest.main()
