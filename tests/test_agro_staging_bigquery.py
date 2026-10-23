"""Contrato E2E: IMEA/CONAB em BigQuery staging com referencia NULL."""
from __future__ import annotations

import json
import sys
import tempfile
import types
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

from nivon.ingestao_fontes_reais import gravar_lote
from nivon.agro_staging_bigquery import (
    ErroStagingAgro, TIPOS, exportar_quarentena, verificar_jsonl,
    arquivar_stage_quarentena, carregar_stage,
)


class Objeto:
    def __init__(self,bytes_,metadata):
        self.size=len(bytes_)
        self.metadata=metadata


class Bucket:
    def __init__(self):
        self.objects={}
    def get_blob(self,key):
        x=self.objects.get(key)
        return Objeto(*x) if x is not None else None
    def blob(self,key):
        parent=self
        class Blob:
            metadata={}
            def upload_from_filename(self,path,content_type,if_generation_match,checksum,timeout):
                assert if_generation_match==0
                assert checksum=="crc32c"
                if key in parent.objects:
                    raise AssertionError("sobrescrita")
                parent.objects[key]=(Path(path).read_bytes(),dict(self.metadata))
        return Blob()


class Storage:
    def __init__(self):
        self.bucket_obj=Bucket()
    def bucket(self,name):
        assert name=="nivon-raw-archive"
        return self.bucket_obj


class Job:
    def result(self,timeout=None):
        return self


class FakeBQ:
    def __init__(self):
        self.sql=None
        self.deleted=False
        self.lines=0
        self.bytes_estimada=24
        self.dry_runs=0
        self.merges=0
    def get_dataset(self,ref):
        assert ref=="nivon-data.nivon_raw"
    def get_table(self,ref):
        assert ref=="nivon-data.nivon_raw.agro_publicacoes_staging"
        return types.SimpleNamespace(
            schema=[types.SimpleNamespace(name=k,field_type=v) for k,v in TIPOS.items()],
            time_partitioning=types.SimpleNamespace(field="data_coleta"),
            require_partition_filter=True)
    def load_table_from_file(self,fp,stage,job_config):
        assert "_agro_stage_" in stage
        self.lines=len(fp.read().splitlines())
        return Job()
    def query(self,sql,job_config):
        self.sql=sql
        assert "@inicio" in sql and "@fim" in sql
        if getattr(job_config,"dry_run",False):
            self.dry_runs+=1
            return types.SimpleNamespace(total_bytes_processed=self.bytes_estimada)
        assert job_config.maximum_bytes_billed==100_000_000
        self.merges+=1
        return Job()
    def delete_table(self,stage,not_found_ok=False):
        assert not_found_ok
        self.deleted=True


def fake_google():
    b=types.ModuleType("google.cloud.bigquery")
    b.SourceFormat=types.SimpleNamespace(NEWLINE_DELIMITED_JSON="NEWLINE_DELIMITED_JSON")
    b.WriteDisposition=types.SimpleNamespace(WRITE_TRUNCATE="WRITE_TRUNCATE")
    b.LoadJobConfig=lambda **kw:types.SimpleNamespace(**kw)
    b.QueryJobConfig=lambda **kw:types.SimpleNamespace(**kw)
    b.SchemaField=lambda k,t:types.SimpleNamespace(name=k,field_type=t)
    b.ScalarQueryParameter=lambda *args:args
    cloud=types.ModuleType("google.cloud")
    cloud.bigquery=b
    google=types.ModuleType("google")
    google.cloud=cloud
    return {"google":google,"google.cloud":cloud,"google.cloud.bigquery":b}


class TestStagingBQ(unittest.TestCase):
    def setUp(self):
        tmp=tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root=Path(tmp.name)
        self.db=self.root/"dados.sqlite"
        self.raw=self.root/"raw"
        self.jsonl=self.root/"quarentena.jsonl"

    def inserir(self,ds="IMEA_PUBLICACOES_STAGING",estado="QUARANTINED",
                ref=None):
        return gravar_lote(
            banco=self.db,diretorio_bruto=self.raw,dataset_id=ds,
            origem="https://api1.imea.com.br/api/v2/mobile/cadeias/4/cotacoes",
            raw=json.dumps({"fonte":ds}).encode(),tipo="application/json",
            coletado_em=datetime(2026,10,23,16,tzinfo=timezone.utc),
            estado=estado,registros=[{
                "identidade":"indicador-1",
                "referencia":"2026-10-22",
                "publicacao":"2026-10-22T12:00:00-04:00",
                "competencia":"26/27",
                "natureza":"INFORMADO",
                "unidade":"R$/sc","valor":"125.50",
                "campos":{"data_referencia":ref,
                          "tipo_referencia":"PUBLICACAO_NAO_EQUIVALE_DATA_REFERENCIA"}
            }])

    def test_exporta_staging_sem_inventar_referencia(self):
        self.inserir()
        saida=exportar_quarentena(
            banco=self.db,destino=self.jsonl,
            fonte_dataset="IMEA_PUBLICACOES_STAGING")
        self.assertEqual(saida["quantidade"],1)
        row=json.loads(self.jsonl.read_text().splitlines()[0])
        self.assertIsNone(row["data_referencia"])
        self.assertEqual(row["data_publicacao"],"2026-10-22")
        self.assertEqual(row["referencia_tecnica"],"2026-10-22")
        self.assertEqual(row["estado"],"QUARANTINED")
        v=verificar_jsonl(
            arquivo=self.jsonl,fonte_dataset="IMEA_PUBLICACOES_STAGING",
            projeto="nivon-data",dataset="nivon_raw")
        self.assertEqual(v["linhas"],1)

    def test_recusa_promocao_e_referencia_inventada(self):
        self.inserir(estado="NORMALIZED")
        with self.assertRaises(ErroStagingAgro):
            exportar_quarentena(
                banco=self.db,destino=self.jsonl,
                fonte_dataset="IMEA_PUBLICACOES_STAGING")
        # Outro banco com referencia inventada segue bloqueado.
        other=self.root/"outro"
        other.mkdir()
        gravar_lote(
            banco=other/"dados.sqlite",diretorio_bruto=other/"raw",
            dataset_id="CONAB_SAFRAS_STAGING",
            origem="https://www.gov.br/conab/pt-br/assuntos/safra",
            raw=b"abc",tipo="application/json",
            coletado_em=datetime(2026,10,23,tzinfo=timezone.utc),
            estado="QUARANTINED",registros=[{
                "identidade":"soja-2025","referencia":"2026-10-20",
                "natureza":"INFORMADO",
                "campos":{"data_referencia":"2026-10-20",
                          "tipo_referencia":"PUBLICACAO_NAO_EQUIVALE_DATA_REFERENCIA"}}])
        with self.assertRaises(ErroStagingAgro):
            exportar_quarentena(
                banco=other/"dados.sqlite",destino=other/"out.jsonl",
                fonte_dataset="CONAB_SAFRAS_STAGING")

    def test_gcs_antes_bigquery_e_merge_particionado(self):
        self.inserir()
        exportar_quarentena(
            banco=self.db,destino=self.jsonl,
            fonte_dataset="IMEA_PUBLICACOES_STAGING")
        storage=Storage()
        archive=arquivar_stage_quarentena(
            arquivo=self.jsonl,bucket="nivon-raw-archive",
            project_id="nivon-data",client=storage)
        self.assertTrue(archive["gcs_executado"])
        same=arquivar_stage_quarentena(
            arquivo=self.jsonl,bucket="nivon-raw-archive",
            project_id="nivon-data",client=storage)
        self.assertEqual(same["estado"],"EXISTENTE_CONFERIDO")
        bq=FakeBQ()
        with patch.dict(sys.modules,fake_google()):
            result=carregar_stage(
                arquivo=self.jsonl,fonte_dataset="IMEA_PUBLICACOES_STAGING",
                project_id="nivon-data",dataset_id="nivon_raw",
                executar=True,client=bq)
        self.assertTrue(result["bigquery_executado"])
        self.assertFalse(result["promocao_canonica"])
        self.assertTrue(bq.deleted)
        self.assertEqual(bq.lines,1)
        self.assertEqual(bq.dry_runs,1)
        self.assertEqual(bq.merges,1)
        self.assertEqual(result["bytes_estimados"],24)
        self.assertIn("DATE(T.data_coleta) BETWEEN @inicio AND @fim",bq.sql)
        self.assertIn("agro_publicacoes_staging",bq.sql)

    def test_merges_bloqueados_com_estimativa_ausente_ou_acima_limite(self):
        self.inserir()
        exportar_quarentena(
            banco=self.db,destino=self.jsonl,
            fonte_dataset="IMEA_PUBLICACOES_STAGING")
        for estimativa in (None,100_000_001,-1):
            with self.subTest(estimativa=estimativa):
                bq=FakeBQ()
                bq.bytes_estimada=estimativa
                with patch.dict(sys.modules,fake_google()):
                    with self.assertRaises(ErroStagingAgro):
                        carregar_stage(
                            arquivo=self.jsonl,
                            fonte_dataset="IMEA_PUBLICACOES_STAGING",
                            project_id="nivon-data",dataset_id="nivon_raw",
                            executar=True,client=bq)
                self.assertEqual(bq.dry_runs,1)
                self.assertEqual(bq.merges,0)
                self.assertTrue(bq.deleted)

    def test_bigquery_rejeita_linha_com_data_referencia(self):
        self.inserir()
        exportar_quarentena(
            banco=self.db,destino=self.jsonl,
            fonte_dataset="IMEA_PUBLICACOES_STAGING")
        obj=json.loads(self.jsonl.read_text())
        obj["data_referencia"]="2026-10-22"
        self.jsonl.write_text(json.dumps(obj)+"\n")
        with self.assertRaises(ErroStagingAgro):
            verificar_jsonl(
                arquivo=self.jsonl,fonte_dataset="IMEA_PUBLICACOES_STAGING",
                projeto="nivon-data",dataset="nivon_raw")

    def test_bigquery_nao_executa_sem_switch(self):
        self.inserir()
        exportar_quarentena(
            banco=self.db,destino=self.jsonl,
            fonte_dataset="IMEA_PUBLICACOES_STAGING")
        with self.assertRaises(PermissionError):
            carregar_stage(arquivo=self.jsonl,
                fonte_dataset="IMEA_PUBLICACOES_STAGING",
                project_id="nivon-data",dataset_id="nivon_raw",
                executar=False)

if __name__=="__main__":
    unittest.main()
