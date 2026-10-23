"""Fluxo Neon legado -> BigQuery: contratos deterministas e sem acesso GCP."""
from datetime import datetime
from decimal import Decimal
import json
import os
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from scripts.nivon_gcp_migracao import (
    MigracaoBloqueada, DATASETS, normalizar, extrair, validar_arquivo,
    carregar_bigquery, _endpoint,
)

ENDPOINT="https://br-twilight-cell-b77ukd6x-nivonlegacy.compute.c-13.us-east-1.aws.neon.tech"


def record(dataset, ident=1, value="150.123456789"):
    base={"id":ident,"source_key":"a"*64,"version_hash":"b"*64}
    if dataset=="imea":
        base.update({"chain":"soja","indicator_id":"718","unit":"R$/sc",
            "price":Decimal(value),"reference_date":None,
            "published_at":"2026-10-22T00:00:00",
            "first_collected_at":"2026-10-23T11:00:00+00:00",
            "quality_status":"PUBLISHED_DATE_ONLY"})
    elif dataset=="cepea":
        base.update({"series_id":"soja_parana","reference_date":"2026-10-21",
            "published_at":None,"collected_at":"2026-10-22T21:18:00+00:00",
            "price_brl":Decimal(value),"quality_status":"VALIDADO",
            "epistemic_type":"INFORMADO"})
    elif dataset=="conab_balancos":
        base.update({"publication_date":"2026-10-15",
           "collected_at":"2026-10-22T00:37:00+00:00",
           "production_mil_t":Decimal(value),"epistemic_type":"INFORMADO"})
    elif dataset=="conab_safras":
        base.update({"reference_date":None,"published_on":"2026-10-15",
           "collected_at":"2026-10-22T00:37:00+00:00",
           "competence":"2025/26","area_mil_ha":Decimal(value),
           "epistemic_type":"INFORMADO"})
    else:
        base.update({"reference_date":None,"published_on":"2026-10-15",
           "collected_at":"2026-10-22T00:37:00+00:00",
           "competence":"2024/25","production_mil_t":Decimal(value),
           "epistemic_type":"INFORMADO"})
    return base


def wrapped(dataset,n=1):
    def decimal_to_json(x):
        if isinstance(x,Decimal):return float(x)
        raise TypeError
    value=record(dataset,n)
    return {"id":str(n),"payload_json":json.dumps(value,default=decimal_to_json)}


class MigrationContracts(unittest.TestCase):
    def test_all_5_sources_no_date_invention(self):
        self.assertEqual(len(DATASETS),5)
        for dataset in DATASETS:
            with self.subTest(dataset=dataset):
                out=normalizar(dataset,wrapped(dataset))
                self.assertIsNone(out["origem_sha256"])
                self.assertEqual(out["id_legado"],1)
                self.assertEqual(out["data_coleta"],"2026-10-23T11:00:00Z" if dataset=="imea" else
                  "2026-10-22T21:18:00Z" if dataset=="cepea" else "2026-10-22T00:37:00Z")
                self.assertEqual(len(out["id_registro"]),64)
                self.assertEqual(len(out["payload_sha256"]),64)
                if dataset=="imea":
                    self.assertIsNone(out["data_referencia"])
                    self.assertEqual(out["tipo_referencia"],"PUBLICACAO_SEM_REFERENCIA")
                    self.assertEqual(out["data_particao"],"2026-10-22")
                    self.assertIsNone(out["competencia"])
                if dataset=="cepea":
                    self.assertEqual(out["data_referencia"],"2026-10-21")
                    self.assertIsNone(out["data_publicacao"])
                if dataset.startswith("conab"):
                    self.assertIsNone(out["data_referencia"])
    def test_decimal_exactitude(self):
        raw='{"id":1,"source_key":"abc","version_hash":"def","reference_date":"2026-10-21","published_at":null,"collected_at":"2026-10-22T21:18:00+00:00","price_brl":150.123456789123456789}'
        out=normalizar("cepea",{"id":"1","payload_json":raw})
        self.assertIn('"150.123456789123456789"',out["payload_json"])
    def test_api_allowlist(self):
        self.assertEqual(_endpoint(ENDPOINT),ENDPOINT)
        for bad in ("http://"+ENDPOINT[8:],ENDPOINT+"?token=abc",
                    "https://api1.imea.com.br","https://example.com"):
            with self.subTest(url=bad),self.assertRaises(MigracaoBloqueada):
                _endpoint(bad)
    def test_future_coleta_sem_fuso(self):
        obj=record("imea")
        obj["first_collected_at"]="2026-10-23T11:00:00"
        with self.assertRaises(MigracaoBloqueada):
            normalizar("imea",{"id":"1","payload_json":json.dumps(obj,default=str)})
    def test_export_to_private_file_and_integrity(self):
        dataset="imea"
        examples=[wrapped(dataset,1),wrapped(dataset,2)]
        def api(base,token,path,params):
            if path=="/checkpoint":
                return {"status":"CHECKPOINT","dataset":dataset,"upper_id":"2","count":2}
            subset=[x for x in examples if int(x["id"])>int(params["after"])]
            return {"status":"OK","dataset":dataset,"upper_id":"2",
                "after_id":params["after"],"rows":subset,"received":len(subset),
                "next_after_id":subset[-1]["id"] if subset else params["after"]}
        with TemporaryDirectory() as directory:
            dest=Path(directory)/"private.jsonl"
            result=extrair(dataset,ENDPOINT,"bearer",dest,api=api)
            self.assertEqual(result["rows"],2)
            self.assertFalse(result["google_cloud_loaded"])
            self.assertEqual(dest.stat().st_mode & 0o777,0o600)
            self.assertEqual(validar_arquivo(dest)["rows"],2)
            with self.assertRaises(MigracaoBloqueada):
                extrair(dataset,ENDPOINT,"bearer",dest,api=api)
    def test_tampered_hash(self):
        with TemporaryDirectory() as d:
            path=Path(d)/"file.jsonl"
            item=normalizar("imea",wrapped("imea"))
            item["payload_sha256"]="0"*64
            path.write_text(json.dumps(item)+"\n")
            path.chmod(0o600)
            with self.assertRaises(MigracaoBloqueada):
                validar_arquivo(path)
    def test_never_load_before_cost_and_auth_approval(self):
        with TemporaryDirectory() as d:
            path=Path(d)/"file.jsonl"
            path.write_text(json.dumps(normalizar("imea",wrapped("imea")))+"\n")
            path.chmod(0o600)
            with patch.dict(os.environ,{"NIVON_GCP_WRITE_APPROVED":"false","NIVON_GCP_COST_REVIEWED":"false"}):
                with self.assertRaises(PermissionError):
                    carregar_bigquery(path)

if __name__=="__main__":
    unittest.main()
