#!/usr/bin/env python3
"""Coletor oficial PTAX BCB -> BigQuery sem dependencia de Neon.

Executa consulta primaria read-only; escrita exige WIF GCP e dois gates.
Nao substitui a historia ja migrada; MERGE por quote_id evita sobreposicoes.
"""
from __future__ import annotations
from datetime import datetime,timezone,timedelta
from decimal import Decimal
from hashlib import sha256
import argparse
import json
import os
from pathlib import Path
import re
import sys
from urllib.parse import urlencode,urlsplit
from urllib.request import Request,urlopen

from scripts.ptax_neon_to_bigquery_jsonl import normalize,InvalidQuote

HOST="https://olinda.bcb.gov.br/olinda/servico/PTAX/versao/v1/odata/"
PROJECT="nivon-data"
TARGET="nivon-data.nivon_core.ptax_quotes"
CURRENCIES=("USD","EUR")
MAX_BILLED_BYTES=1_073_741_824
COLUMNS=("quote_id","currency","reference_date","quote_time_original","bulletin_type",
"buy_brl","sell_brl","unit","source","license","published_at","first_collected_at",
"last_verified_at","observation_kind","record_sha256","origem_sha256","vintage_id",
"source_neon_row_id","migration_schema_version","quality_status")
ROOT=Path(__file__).resolve().parents[1]


class FonteBCPBloqueada(ValueError):pass


def url_bcb(moeda:str,comeco:str,fim:str)->str:
    if moeda not in CURRENCIES:raise FonteBCPBloqueada("MOEDA_INVALIDA")
    for x in (comeco,fim):
        if not re.fullmatch(r"20\d{2}-\d{2}-\d{2}",x):
            raise FonteBCPBloqueada("JANELA_INVALIDA")
    if comeco>fim:raise FonteBCPBloqueada("JANELA_INVERTIDA")
    ptax_date=lambda value:value[5:7]+"-"+value[8:10]+"-"+value[:4]
    args={"@dataInicial":"'"+ptax_date(comeco)+"'",
          "@dataFinalCotacao":"'"+ptax_date(fim)+"'","$format":"json","$top":"5000"}
    if moeda=="USD":
        method="CotacaoDolarPeriodo(dataInicial=@dataInicial,dataFinalCotacao=@dataFinalCotacao)"
    else:
        method="CotacaoMoedaPeriodo(moeda=@moeda,dataInicial=@dataInicial,dataFinalCotacao=@dataFinalCotacao)"
        args["@moeda"]="'EUR'"
    return HOST+method+"?"+urlencode(args)


def coletar(moeda:str,comeco:str,fim:str,*,opener=urlopen,agora=None)->list[dict]:
    uri=url_bcb(moeda,comeco,fim)
    req=Request(uri,headers={"Accept":"application/json","User-Agent":"NIVON-GCP/1.0"})
    with opener(req,timeout=22) as resp:
        final=urlsplit(resp.geturl())
        if final.scheme!="https" or final.hostname!="olinda.bcb.gov.br":
            raise FonteBCPBloqueada("REDIRECT_FORA_DO_BCB")
        raw=resp.read(2_000_001)
    if len(raw)>2_000_000:raise FonteBCPBloqueada("ODATA_LARGE_RESPONSE")
    try:
        body=json.loads(raw,parse_float=Decimal)
    except ValueError:raise FonteBCPBloqueada("ODATA_INVALID_JSON") from None
    if not isinstance(body,dict) or not isinstance(body.get("value"),list) or        len(body["value"])>=5000 or body.get("@odata.nextLink") or body.get("odata.nextLink"):
        raise FonteBCPBloqueada("ODATA_PARTIAL_OR_INVALID")
    timestamp=(agora or datetime.now(timezone.utc)).astimezone(timezone.utc)
    if timestamp.utcoffset() is None:raise FonteBCPBloqueada("COLLECTION_WITHOUT_TZ")
    utc=timestamp.isoformat().replace("+00:00","Z")
    quotes=[];seen=set()
    for original in body["value"]:
        if not isinstance(original,dict):raise FonteBCPBloqueada("ODATA_ROW_INVALID")
        quote_time=original.get("dataHoraCotacao")
        bulletin="COTACAO_DOLAR_DIARIA" if moeda=="USD" else original.get("tipoBoletim")
        if not isinstance(quote_time,str) or not re.match(r"^20\d{2}-\d{2}-\d{2}[ T]\d{2}:\d{2}:\d{2}",quote_time) or            not isinstance(bulletin,str) or not bulletin:
            raise FonteBCPBloqueada("ODATA_TIME_OR_BULLETIN_INVALID")
        ref=quote_time[:10]
        if ref<comeco or ref>fim:
            raise FonteBCPBloqueada("ODATA_QUOTE_OUTSIDE_WINDOW")
        row={"id":None,"currency":moeda,"reference_date":ref,
             "quote_time_original":quote_time,"bulletin_type":bulletin,
             "buy_brl":original.get("cotacaoCompra"),"sell_brl":original.get("cotacaoVenda"),
             "unit":"BRL/"+moeda,"source":"Banco Central do Brasil / PTAX",
             "license":"ODbL","published_at":None,
             "first_collected_at":utc,"last_verified_at":utc,
             "observation_kind":"INFORMADO"}
        try:mapped=normalize(row)
        except InvalidQuote:raise FonteBCPBloqueada("BCB_VALIDATION_FAILED") from None
        if mapped["quote_id"] in seen:raise FonteBCPBloqueada("ODATA_DUPLICATE")
        seen.add(mapped["quote_id"])
        mapped["quality_status"]="BCB_PRIMARIO_INFORMADO"
        mapped["migration_schema_version"]="2.0.0"
        mapped["origem_sha256"]=None # Hash byte a byte do payload OData nao foi preservado.
        quotes.append(mapped)
    return quotes


def salvar(resultados:list[dict],output:Path)->dict:
    if not resultados:raise FonteBCPBloqueada("BCB_NO_QUOTES_IN_WINDOW")
    if output.is_symlink() or output.exists() or output.resolve().is_relative_to(ROOT):
        raise FonteBCPBloqueada("OUTPUT_NOT_PRIVATE")
    output.parent.mkdir(parents=True,exist_ok=True,mode=0o700)
    flags=os.O_WRONLY|os.O_CREAT|os.O_EXCL
    fd=os.open(output,flags,0o600)
    try:
        with os.fdopen(fd,"w",encoding="utf-8") as f:
            for row in resultados:
                if set(row)!=set(COLUMNS):raise FonteBCPBloqueada("TARGET_SCHEMA_INVALID")
                f.write(json.dumps(row,ensure_ascii=False,separators=(",",":"))+"\n")
    except BaseException:
        output.unlink(missing_ok=True)
        raise
    return {"status":"BCB_SOURCE_VALIDATED_NOT_LOADED","rows":len(resultados),
        "counts":{x:sum(r["currency"]==x for r in resultados) for x in CURRENCIES},
        "bigquery_loaded":False}


def load_gcp(path:Path)->dict:
    if os.getenv("NIVON_GCP_WRITE_APPROVED")!="true" or os.getenv("NIVON_GCP_COST_REVIEWED")!="true":
        raise PermissionError("GCP_WRITE_DISABLED")
    from google.cloud import bigquery
    from uuid import uuid4
    client=bigquery.Client(project=PROJECT)
    table=client.get_table(TARGET)
    if table.time_partitioning is None or table.time_partitioning.field!="reference_date" or        not table.require_partition_filter or set(x.name for x in table.schema)!=set(COLUMNS):
        raise FonteBCPBloqueada("BQ_PTAX_SCHEMA_INVALID")
    rows=[json.loads(x) for x in path.read_text(encoding="utf8").splitlines()]
    if not rows or any(x.get("quality_status")!="BCB_PRIMARIO_INFORMADO" or
                       x.get("source_neon_row_id") is not None for x in rows):
        raise FonteBCPBloqueada("BCB_TARGET_ROW_INVALID")
    dates=[r["reference_date"] for r in rows]
    start,end=min(dates),max(dates)
    stage="nivon-data.nivon_core._ptax_bcb_"+uuid4().hex[:18]
    config=bigquery.LoadJobConfig(schema=table.schema,
      source_format=bigquery.SourceFormat.NEWLINE_DELIMITED_JSON,
      write_disposition=bigquery.WriteDisposition.WRITE_EMPTY)
    pars=[bigquery.ScalarQueryParameter("start","DATE",start),
          bigquery.ScalarQueryParameter("end","DATE",end)]
    conf=lambda dry:bigquery.QueryJobConfig(query_parameters=pars,
      dry_run=dry,maximum_bytes_billed=MAX_BILLED_BYTES)
    fields=",".join(COLUMNS)
    refs=",".join("S."+x for x in COLUMNS)
    merge=f"""MERGE `{TARGET}` T USING `{stage}` S
      ON T.quote_id=S.quote_id AND T.reference_date=S.reference_date
      AND T.reference_date BETWEEN @start AND @end
      WHEN NOT MATCHED THEN INSERT ({fields}) VALUES ({refs})"""
    diff=f"""SELECT COUNT(*) AS missing FROM `{stage}` S
      LEFT JOIN `{TARGET}` T ON T.quote_id=S.quote_id
      AND T.reference_date=S.reference_date AND T.reference_date BETWEEN @start AND @end
      WHERE T.quote_id IS NULL"""
    dup=f"""SELECT COUNT(*) AS duplicates FROM (
      SELECT quote_id FROM `{TARGET}` WHERE reference_date BETWEEN @start AND @end
      GROUP BY quote_id HAVING COUNT(*)>1)"""
    try:
        with path.open("rb") as f:
            client.load_table_from_file(f,stage,job_config=config).result(timeout=180)
        for statement in (merge,diff,dup):client.query(statement,job_config=conf(True))
        client.query(merge,job_config=conf(False)).result(timeout=180)
        result=list(client.query(diff,job_config=conf(False)).result(timeout=180))
        duplicates=list(client.query(dup,job_config=conf(False)).result(timeout=180))
        if len(result)!=1 or result[0]["missing"] or len(duplicates)!=1 or duplicates[0]["duplicates"]:
            raise FonteBCPBloqueada("PTAX_BQ_RECONCILIATION_FAILED")
        return {"status":"BCB_BIGQUERY_MERGE_VERIFIED","rows":len(rows),
                "dates":[start,end],"gcp_written":True,"neon_used":False}
    finally:
        client.delete_table(stage,not_found_ok=True)


def main(argv=None):
    p=argparse.ArgumentParser()
    p.add_argument("--arquivo",required=True,type=Path)
    p.add_argument("--carregar",action="store_true")
    p.add_argument("--dias",type=int,default=10)
    a=p.parse_args(argv)
    try:
        if a.dias<1 or a.dias>31:raise FonteBCPBloqueada("DAYS_RANGE_INVALID")
        now=datetime.now(timezone.utc)
        end=now.date()
        begin=end-timedelta(days=a.dias)
        rows=[]
        for currency in CURRENCIES:
            rows+=coletar(currency,begin.isoformat(),end.isoformat(),agora=now)
        report=salvar(rows,a.arquivo)
        if a.carregar:
            report=load_gcp(a.arquivo)
        print(json.dumps(report,ensure_ascii=False))
        return 0
    except (FonteBCPBloqueada,PermissionError,OSError) as exc:
        code=str(exc) if isinstance(exc,(FonteBCPBloqueada,PermissionError)) else type(exc).__name__
        print("BCB_GCP_BLOCKED:"+code,file=sys.stderr)
        return 3
if __name__=="__main__":raise SystemExit(main())
