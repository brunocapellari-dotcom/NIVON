#!/usr/bin/env python3
"""PTAX NIVON: planejar e executar lote privado Neon -> BigQuery com gates.

Sem --executar e duas aprovacoes em ambiente, ZERO chamadas Google Cloud.
A carga real exige OIDC/ADC previamente configurado, dataset/tabela existentes,
limite de bytes e reconciliação completa do lote; não desliga Neon.
"""
from __future__ import annotations
from collections import Counter
from datetime import date
from decimal import Decimal
from hashlib import sha256
import json
import os
from pathlib import Path
import re
import sys
import uuid

from scripts.ptax_neon_to_bigquery_jsonl import normalize, InvalidQuote

ROOT=Path(__file__).resolve().parents[1]
COLUMNS=("quote_id","currency","reference_date","quote_time_original","bulletin_type",
 "buy_brl","sell_brl","unit","source","license","published_at","first_collected_at",
 "last_verified_at","observation_kind","record_sha256","origem_sha256","vintage_id",
 "source_neon_row_id","migration_schema_version","quality_status")
MAX_FILE_BYTES=65_000_000
MAX_ROWS=100_000
MAX_BILLED_BYTES=1_073_741_824
PROJECT="nivon-data"
DATASET="nivon_core"
TABLE="ptax_quotes"

class CargaBloqueada(ValueError):pass

def _source_from_target(row):
    return {"id":row["source_neon_row_id"],"currency":row["currency"],
        "reference_date":row["reference_date"],"quote_time_original":row["quote_time_original"],
        "bulletin_type":row["bulletin_type"],"buy_brl":row["buy_brl"],
        "sell_brl":row["sell_brl"],"unit":row["unit"],"source":row["source"],
        "license":row["license"],"published_at":row["published_at"],
        "first_collected_at":row["first_collected_at"],"last_verified_at":row["last_verified_at"],
        "observation_kind":row["observation_kind"]}

def planejar(path:Path)->dict:
    path=Path(path)
    if path.is_symlink() or not path.is_file():
        raise CargaBloqueada("FILE_NOT_PRIVATE_OR_MISSING")
    path=path.resolve()
    if path.is_relative_to(ROOT):
        raise CargaBloqueada("DATA_INSIDE_PUBLIC_REPOSITORY")
    st=path.stat()
    if st.st_size<=0 or st.st_size>MAX_FILE_BYTES or (st.st_mode&0o077)!=0:
        raise CargaBloqueada("FILE_SIZE_OR_PERMISSIONS")
    seen_quotes=set(); seen_ids=set(); counts=Counter(); ref_min=None;ref_max=None
    digest=sha256();last_id=0;n=0
    with path.open("rb") as fd:
        for raw_line in fd:
            n+=1
            if n>MAX_ROWS or not raw_line.strip():
                raise CargaBloqueada("MAX_ROWS_OR_EMPTY_LINE")
            digest.update(raw_line)
            try:
                row=json.loads(raw_line.decode("utf-8"),parse_float=Decimal)
                if not isinstance(row,dict) or set(row)!=set(COLUMNS):
                    raise CargaBloqueada("BQ_SCHEMA_MISMATCH")
                if not isinstance(row["source_neon_row_id"],int) or isinstance(row["source_neon_row_id"],bool):
                    raise CargaBloqueada("SOURCE_ID_INVALID")
                row_id=row["source_neon_row_id"]
                if row_id<=last_id or row_id in seen_ids:
                    raise CargaBloqueada("SOURCE_IDS_NOT_STRICTLY_INCREASING")
                last_id=row_id
                expected=normalize(_source_from_target(row))
                if expected!=row:
                    raise CargaBloqueada("BQ_ROW_HASH_OR_PROVENANCE_MISMATCH")
                if row["quality_status"]!="NEON_EXPORT_UNVERIFIED":
                    raise CargaBloqueada("INVALID_QUALITY_GATE")
                ref=date.fromisoformat(row["reference_date"])
            except (ValueError,TypeError,KeyError,UnicodeError,InvalidQuote) as exc:
                if isinstance(exc,CargaBloqueada):raise
                raise CargaBloqueada("INVALID_JSONL_ROW") from None
            if row["quote_id"] in seen_quotes:
                raise CargaBloqueada("DUPLICATE_BUSINESS_QUOTE")
            seen_quotes.add(row["quote_id"]);seen_ids.add(row_id)
            counts[row["currency"]]+=1
            if ref_min is None or ref<ref_min:ref_min=ref
            if ref_max is None or ref>ref_max:ref_max=ref
    if n==0:raise CargaBloqueada("EMPTY_FILE")
    return {"status":"VALIDATED_PRIVATE_BATCH_NOT_LOADED","project":PROJECT,
       "target":f"{PROJECT}.{DATASET}.{TABLE}","rows":n,
       "count_by_currency":dict(counts),"first_reference":ref_min.isoformat(),
       "last_reference":ref_max.isoformat(),"max_neon_row_id":last_id,
       "file_sha256":digest.hexdigest(),"bigquery_executed":False,
       "cutover_approved":False,"max_bytes_billed":MAX_BILLED_BYTES}

def executar(path:Path,*,client=None,approve:bool=False)->dict:
    plan=planejar(path)
    if approve is not True or os.getenv("NIVON_GCP_WRITE_APPROVED")!="true" or os.getenv("NIVON_GCP_COST_REVIEWED")!="true":
        raise PermissionError("BIGQUERY_WRITE_NOT_APPROVED")
    try:
        from google.cloud import bigquery
    except ImportError:
        raise CargaBloqueada("BIGQUERY_SDK_NOT_INSTALLED") from None
    cli=client or bigquery.Client(project=PROJECT)
    target=f"{PROJECT}.{DATASET}.{TABLE}"
    cli.get_dataset(f"{PROJECT}.{DATASET}")
    target_table=cli.get_table(target)
    if (target_table.time_partitioning is None or
        target_table.time_partitioning.field!="reference_date" or
        not target_table.require_partition_filter or
        {f.name for f in target_table.schema}!=set(COLUMNS)):
        raise CargaBloqueada("TARGET_SCHEMA_OR_PARTITION_MISMATCH")
    staging=f"{PROJECT}.{DATASET}._ptax_bridge_{uuid.uuid4().hex[:22]}"
    config=bigquery.LoadJobConfig(
      schema=target_table.schema,
      source_format=bigquery.SourceFormat.NEWLINE_DELIMITED_JSON,
      create_disposition=bigquery.CreateDisposition.CREATE_IF_NEEDED,
      write_disposition=bigquery.WriteDisposition.WRITE_EMPTY)
    date_start,date_end=plan["first_reference"],plan["last_reference"]
    params=[bigquery.ScalarQueryParameter("first","DATE",date_start),
            bigquery.ScalarQueryParameter("last","DATE",date_end)]
    merge=f"""MERGE `{target}` AS T USING `{staging}` AS S
      ON T.quote_id=S.quote_id AND T.reference_date=S.reference_date
      AND T.reference_date BETWEEN @first AND @last
      WHEN NOT MATCHED THEN
      INSERT ({','.join(COLUMNS)}) VALUES ({','.join('S.'+k for k in COLUMNS)})"""
    validate=f"""SELECT
      COUNTIF(T.quote_id IS NULL OR T.record_sha256!=S.record_sha256) AS mismatches
      FROM `{staging}` S
      LEFT JOIN `{target}` T
      ON S.quote_id=T.quote_id AND S.reference_date=T.reference_date
      AND T.reference_date BETWEEN @first AND @last"""
    duplicates=f"""SELECT COUNT(*) AS duplicate_keys FROM (
      SELECT quote_id FROM `{target}` T
      WHERE T.reference_date BETWEEN @first AND @last
        AND T.quote_id IN (SELECT quote_id FROM `{staging}`)
      GROUP BY quote_id HAVING COUNT(*)>1)"""
    query_config=lambda dry:bigquery.QueryJobConfig(
        query_parameters=params,maximum_bytes_billed=MAX_BILLED_BYTES,dry_run=dry)
    try:
        with Path(path).open("rb") as f:
            cli.load_table_from_file(f,staging,job_config=config).result(timeout=180)
        for q in (merge,validate,duplicates):
            cli.query(q,job_config=query_config(True))  # conferir custo ANTES de executar DML
        cli.query(merge,job_config=query_config(False)).result(timeout=180)
        r=next(iter(cli.query(validate,job_config=query_config(False)).result(timeout=180)))
        d=next(iter(cli.query(duplicates,job_config=query_config(False)).result(timeout=180)))
        if int(r["mismatches"])!=0 or int(d["duplicate_keys"])!=0:
            raise CargaBloqueada("BIGQUERY_RECONCILIATION_FAILED")
        plan.update({"status":"BIGQUERY_BATCH_LOADED_RECONCILED_LOCAL",
            "bigquery_executed":True,"reconciled_batch_rows":plan["rows"],
            "cutover_approved":False,"source_snapshot_transactional":False})
        return plan
    finally:
        # Uma falha parcial de load tambem pode ter criado o objeto temporario.
        cli.delete_table(staging,not_found_ok=True)

def main(argv=None)->int:
    import argparse
    parser=argparse.ArgumentParser(description="Planejamento seguro PTAX BigQuery")
    parser.add_argument("--arquivo",required=True,type=Path)
    parser.add_argument("--executar",action="store_true")
    a=parser.parse_args(argv)
    try:
        r=executar(a.arquivo,approve=True) if a.executar else planejar(a.arquivo)
        print(json.dumps(r,ensure_ascii=False,sort_keys=True))
        return 0
    except (CargaBloqueada,PermissionError,OSError) as e:
        code=str(e) if isinstance(e,(CargaBloqueada,PermissionError)) else "IO_ERROR"
        print("PTAX_BQ_BLOCKED:"+code,file=sys.stderr)
        return 3
if __name__=="__main__":raise SystemExit(main())
