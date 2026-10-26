#!/usr/bin/env python3
"""NIVON: transferencia privada de IMEA, CEPEA e CONAB do Neon para BigQuery.

Sem acesso autenticado ao GCP, permite somente exportar/verificar JSONL privado.
Dados CEPEA/IMEA nao sao declarados precos atuais. Nao altera o Neon.
"""
from __future__ import annotations

import argparse
from datetime import date, datetime, timezone, timedelta
from decimal import Decimal
import hashlib
import json
import os
from pathlib import Path
import re
import sys
from urllib.parse import urlencode, urlsplit
from urllib.request import Request, urlopen
from typing import Any

DATASETS=("imea","cepea","conab_safras","conab_balancos","conab_series")
PROJECT="nivon-data"
TARGET="nivon-data.nivon_stage.neon_legado"
COLUMNS=("id_registro","fonte","dataset_origem","id_legado","chave_origem",
 "hash_versao","payload_sha256","payload_json","data_particao","data_referencia",
 "data_publicacao","data_coleta","competencia","natureza","status_qualidade",
 "source_url","tipo_referencia","origem_sha256")
SCHEMA_TYPES=("STRING","STRING","STRING","INTEGER","STRING","STRING","STRING","STRING",
 "DATE","DATE","DATE","TIMESTAMP","STRING","STRING","STRING","STRING","STRING","STRING")
ALLOWED_HOST=re.compile(r"^br-[a-z0-9-]+-nivonlegacy\.compute\.c-13\.us-east-1\.aws\.neon\.tech$")
AUDIENCE="urn:nivon:legacy:export:v1"
MAX_BYTES=20_000_000
MAX_RECORDS=100_000
MAX_COST_BYTES=1_073_741_824
ROOT=Path(__file__).resolve().parents[1]


class MigracaoBloqueada(ValueError):
    pass


def _int(v: Any,*,zero=False)->int:
    if isinstance(v,bool) or not isinstance(v,(str,int)) or not re.fullmatch(r"(0|[1-9][0-9]*)",str(v)):
        raise MigracaoBloqueada("BAD_ID")
    n=int(v)
    if n>2**53-1 or (n==0 and not zero):raise MigracaoBloqueada("BAD_ID_RANGE")
    return n


def _dt(value: Any) -> str:
    if not isinstance(value,str):
        raise MigracaoBloqueada("MISSING_COLLECTION_DATETIME")
    try:
        result=datetime.fromisoformat(value.replace("Z","+00:00"))
        if result.utcoffset() is None:raise ValueError
        return result.astimezone(timezone.utc).isoformat().replace("+00:00","Z")
    except ValueError:
        raise MigracaoBloqueada("BAD_COLLECTION_TIMEZONE") from None


def _date(value: Any) -> str | None:
    if value is None:return None
    if not isinstance(value,str):
        raise MigracaoBloqueada("INVALID_DATE")
    try:
        s=value[:10]
        if len(s)!=10 or date.fromisoformat(s).isoformat()!=s:raise ValueError
        return s
    except ValueError:
        raise MigracaoBloqueada("INVALID_DATE") from None


def _canonical(data: Any)->Any:
    if isinstance(data,Decimal):
        if not data.is_finite():raise MigracaoBloqueada("INVALID_DECIMAL")
        return format(data,"f")
    if isinstance(data,list):return [_canonical(x) for x in data]
    if isinstance(data,dict):return {str(k):_canonical(v) for k,v in data.items()}
    if isinstance(data,(str,int,bool)) or data is None:return data
    raise MigracaoBloqueada("UNKNOWN_JSON_TYPE")


def _json(data:Any)->str:
    return json.dumps(data,ensure_ascii=False,sort_keys=True,separators=(",",":"))


def normalizar(dataset:str,row:dict)->dict:
    if dataset not in DATASETS or not isinstance(row,dict) or set(row)!={"id","payload_json"}:
        raise MigracaoBloqueada("INVALID_SOURCE_SCHEMA")
    ident=_int(row["id"])
    payload_raw=row["payload_json"]
    if not isinstance(payload_raw,str) or len(payload_raw)>160_000:
        raise MigracaoBloqueada("INVALID_SOURCE_PAYLOAD")
    try:
        original=json.loads(payload_raw,parse_float=Decimal,parse_int=int)
    except (ValueError,TypeError):
        raise MigracaoBloqueada("INVALID_SOURCE_JSON") from None
    if not isinstance(original,dict) or _int(original.get("id"))!=ident:
        raise MigracaoBloqueada("SOURCE_ID_MISMATCH")
    payload=_canonical(original)
    key=payload.get("source_key")
    version=payload.get("version_hash")
    if not isinstance(key,str) or not key or not isinstance(version,str) or not version:
        raise MigracaoBloqueada("MISSING_SOURCE_PROVENANCE")
    ref=_date(payload.get("reference_date"))
    pub_field={
        "imea":"published_at","cepea":"published_at","conab_safras":"published_on",
        "conab_balancos":"publication_date","conab_series":"published_on"
    }[dataset]
    publication=_date(payload.get(pub_field))
    collection_field="first_collected_at" if dataset=="imea" else "collected_at"
    collection=_dt(payload.get(collection_field))
    if dataset=="imea" and ref is not None:
        raise MigracaoBloqueada("IMEA_REFERENCE_UNEXPECTED")
    partition=ref or publication or collection[:10]
    competence=payload.get("competence")
    if competence is not None and (not isinstance(competence,str) or len(competence)>80):
        raise MigracaoBloqueada("INVALID_COMPETENCE")
    if competence is None and ref is not None:
        competence=ref[:7]
    if dataset=="imea":
        nature="INFORMADO"
        quality=str(payload.get("quality_status") or "PUBLICACAO_SEM_REFERENCIA")
    else:
        nature=str(payload.get("epistemic_type") or "INFORMADO")
        quality=str(payload.get("quality_status") or "LEGADO_NAO_HOMOLOGADO")
    source_url=payload.get("source_url") or payload.get("source_uri")
    if source_url is not None and (not isinstance(source_url,str) or len(source_url)>2048):
        raise MigracaoBloqueada("INVALID_SOURCE_URI")
    payload_json=_json(payload)
    digest=hashlib.sha256(payload_json.encode("utf-8")).hexdigest()
    identity=hashlib.sha256(_json([dataset,ident,key,version,partition]).encode()).hexdigest()
    return {
      "id_registro":identity,"fonte":dataset.split("_",1)[0].upper(),
      "dataset_origem":dataset,"id_legado":ident,
      "chave_origem":key,"hash_versao":version,
      "payload_sha256":digest,"payload_json":payload_json,
      "data_particao":partition,"data_referencia":ref,
      "data_publicacao":publication,"data_coleta":collection,
      "competencia":competence,"natureza":nature,
      "status_qualidade":quality,"source_url":source_url,
      "tipo_referencia":("REFERENCIA_INFORMADA" if ref else
                          "PUBLICACAO_SEM_REFERENCIA" if publication else
                          "COLETA_SEM_REFERENCIA"),
      "origem_sha256":None
    }


def _endpoint(raw:str)->str:
    u=urlsplit(raw)
    if u.scheme!="https" or not u.hostname or not ALLOWED_HOST.fullmatch(u.hostname) or        u.username or u.password or u.query or u.fragment or u.path not in ("","/") or u.port not in (None,443):
        raise MigracaoBloqueada("LEGACY_BRIDGE_URL_NOT_ALLOWED")
    return "https://"+u.hostname


def _token(opener=urlopen)->str:
    requrl=os.environ.get("ACTIONS_ID_TOKEN_REQUEST_URL","")
    bearer=os.environ.get("ACTIONS_ID_TOKEN_REQUEST_TOKEN","")
    if not requrl.startswith("https://") or not bearer:
        raise MigracaoBloqueada("GITHUB_OIDC_UNAVAILABLE")
    request=Request(requrl+("&" if "?" in requrl else "?")+urlencode({"audience":AUDIENCE}),
        headers={"Authorization":"Bearer "+bearer})
    with opener(request,timeout=20) as r:
        payload=json.load(r)
    token=payload.get("value")
    if not isinstance(token,str) or not 20<len(token)<12000:
        raise MigracaoBloqueada("OIDC_TOKEN_INVALID")
    return token


def _api(base:str,token:str,path:str,params:dict,opener=urlopen)->dict:
    request=Request(base+path+"?"+urlencode(params),headers={
        "Accept":"application/json","Authorization":"Bearer "+token,
        "Cache-Control":"no-store"})
    with opener(request,timeout=45) as response:
        if response.status!=200:raise MigracaoBloqueada("LEGACY_HTTP_NOT_OK")
        raw=response.read(2_000_001)
    if len(raw)>2_000_000:raise MigracaoBloqueada("LEGACY_PAGE_TOO_LARGE")
    try:payload=json.loads(raw)
    except (ValueError,TypeError):raise MigracaoBloqueada("LEGACY_RESPONSE_INVALID") from None
    if not isinstance(payload,dict):raise MigracaoBloqueada("LEGACY_RESPONSE_INVALID")
    return payload


def extrair(dataset:str,endpoint:str,token:str,saida:Path,*,api=_api)->dict:
    if dataset not in DATASETS or not token:raise MigracaoBloqueada("DATASET_OR_TOKEN_MISSING")
    base=_endpoint(endpoint)
    if saida.is_symlink() or saida.exists() or saida.resolve().is_relative_to(ROOT):
        raise MigracaoBloqueada("PRIVATE_PATH_REQUIRED")
    checkpoint=api(base,token,"/checkpoint",{"dataset":dataset})
    if checkpoint.get("status")!="CHECKPOINT" or checkpoint.get("dataset")!=dataset:
        raise MigracaoBloqueada("LEGACY_CHECKPOINT_INVALID")
    upper=_int(checkpoint.get("upper_id"),zero=True)
    expected=checkpoint.get("count")
    if isinstance(expected,bool) or not isinstance(expected,int) or not 0<=expected<=MAX_RECORDS:
        raise MigracaoBloqueada("LEGACY_COUNT_INVALID")
    if upper==0 and expected:
        raise MigracaoBloqueada("LEGACY_INCONSISTENT_EMPTY")
    if upper==0:
        return {"dataset":dataset,"rows":0,"source_count":0,"status":"EMPTY_NO_LOAD"}
    count=0;last=0
    digest=hashlib.sha256()
    first=None;latest=None
    saida.parent.mkdir(parents=True,exist_ok=True,mode=0o700)
    fd=os.open(saida,os.O_CREAT|os.O_EXCL|os.O_WRONLY,0o600)
    try:
        with os.fdopen(fd,"w",encoding="utf-8") as out:
            while last<upper:
                page=api(base,token,"/export",{
                    "dataset":dataset,"after":str(last),"upto":str(upper),"limit":"80"})
                if page.get("status")!="OK" or page.get("dataset")!=dataset or                    page.get("upper_id")!=str(upper) or page.get("after_id")!=str(last):
                    raise MigracaoBloqueada("LEGACY_PAGE_PROTOCOL")
                rows=page.get("rows")
                if not isinstance(rows,list) or len(rows)>80 or page.get("received")!=len(rows):
                    raise MigracaoBloqueada("LEGACY_PAGE_SHAPE")
                if not rows:break
                for r in rows:
                    next_id=_int(r.get("id")) if isinstance(r,dict) else 0
                    if next_id<=last or next_id>upper:
                        raise MigracaoBloqueada("LEGACY_ID_ORDER")
                    record=normalizar(dataset,r)
                    encoded=(_json(record)+"\n").encode("utf-8")
                    out.write(encoded.decode("utf-8"))
                    digest.update(encoded)
                    count+=1
                    if count>MAX_RECORDS or out.tell()>MAX_BYTES:
                        raise MigracaoBloqueada("LEGACY_EXPORT_LIMIT")
                    day=record["data_particao"]
                    first=min(first,day) if first else day
                    latest=max(latest,day) if latest else day
                    last=next_id
                if page.get("next_after_id")!=str(last):
                    raise MigracaoBloqueada("LEGACY_CURSOR_MISMATCH")
                if len(rows)<80:break
        if count==0 and expected!=0:raise MigracaoBloqueada("LEGACY_EMPTY_WHEN_EXPECTED")
        # Inserts entre checkpoint e ultima pagina sao possiveis: contagem e teto registrados.
        if count!=expected:raise MigracaoBloqueada("LEGACY_SNAPSHOT_COUNT_MISMATCH")
    except BaseException:
        saida.unlink(missing_ok=True)
        raise
    return {"dataset":dataset,"rows":count,"source_count_at_checkpoint":expected,
        "source_max_id":upper,"latest_id_exported":last,"data_particao_inicial":first,
        "data_particao_final":latest,"jsonl_sha256":digest.hexdigest(),
        "snapshot_transactional":False,"google_cloud_loaded":False,
        "status":"EXTRAIDO_PRIVADO_NAO_CARREGADO"}


def validar_arquivo(arquivo:Path)->dict:
    if arquivo.is_symlink() or not arquivo.is_file() or arquivo.resolve().is_relative_to(ROOT):
        raise MigracaoBloqueada("UNSAFE_PRIVATE_FILE")
    if arquivo.stat().st_mode&0o077 or arquivo.stat().st_size>MAX_BYTES:
        raise MigracaoBloqueada("UNSAFE_FILE_PERMISSIONS")
    total=0;seen=set();ds=None;date_min=None;date_max=None
    with arquivo.open("r",encoding="utf-8") as f:
        for line in f:
            if total>=MAX_RECORDS or not line.strip():raise MigracaoBloqueada("FILE_LIMIT")
            row=json.loads(line)
            if set(row)!=set(COLUMNS) or row["dataset_origem"] not in DATASETS:
                raise MigracaoBloqueada("BAD_TARGET_ROW")
            if ds is None:ds=row["dataset_origem"]
            elif ds!=row["dataset_origem"]:raise MigracaoBloqueada("MIXED_DATASETS")
            if row["id_registro"] in seen:raise MigracaoBloqueada("DUPLICATE_ID")
            seen.add(row["id_registro"])
            payload=_json(json.loads(row["payload_json"]))
            # Canonical payload serializado; a hash tem que corresponder exatamente.
            if payload!=row["payload_json"] or hashlib.sha256(payload.encode()).hexdigest()!=row["payload_sha256"]:
                raise MigracaoBloqueada("PAYLOAD_HASH_INVALID")
            if row["origem_sha256"] is not None or                row["tipo_referencia"]=="PUBLICACAO_SEM_REFERENCIA" and row["data_referencia"] is not None:
                raise MigracaoBloqueada("PROVENANCE_OR_TEMPORAL_INCONSISTENCY")
            if row["data_particao"] != (row["data_referencia"] or row["data_publicacao"] or row["data_coleta"][:10]):
                raise MigracaoBloqueada("PARTITION_DATE_MISMATCH")
            day=row["data_particao"];date_min=min(date_min,day) if date_min else day
            date_max=max(date_max,day) if date_max else day
            total+=1
    if total==0:raise MigracaoBloqueada("EMPTY_SOURCE_BATCH")
    return {"dataset":ds,"rows":total,"partition_start":date_min,"partition_end":date_max,
        "status":"VALIDADO_SEM_CARGA"}


def carregar_bigquery(arquivo:Path)->dict:
    report=validar_arquivo(arquivo)
    if os.getenv("NIVON_GCP_WRITE_APPROVED")!="true" or        os.getenv("NIVON_GCP_COST_REVIEWED")!="true":
        raise PermissionError("GCP_WRITES_DISABLED")
    from google.cloud import bigquery
    import uuid
    client=bigquery.Client(project=PROJECT)
    target_table=client.get_table(TARGET)
    if target_table.time_partitioning is None or        target_table.time_partitioning.field!="data_particao" or        not target_table.require_partition_filter or        set(f.name for f in target_table.schema)!=set(COLUMNS):
        raise MigracaoBloqueada("BIGQUERY_TARGET_NOT_PREPARED")
    stage="nivon-data.nivon_stage._mig_"+uuid.uuid4().hex[:18]
    schema=target_table.schema
    cfg=bigquery.LoadJobConfig(schema=schema,
      source_format=bigquery.SourceFormat.NEWLINE_DELIMITED_JSON,
      write_disposition=bigquery.WriteDisposition.WRITE_EMPTY)
    start=report["partition_start"];end=report["partition_end"]
    params=[bigquery.ScalarQueryParameter("start","DATE",start),
            bigquery.ScalarQueryParameter("end","DATE",end)]
    qconf=lambda dry:bigquery.QueryJobConfig(
       query_parameters=params,dry_run=dry,maximum_bytes_billed=MAX_COST_BYTES)
    fields=",".join(COLUMNS)
    cols=",".join("S."+x for x in COLUMNS)
    # Stage tables are private, disposable; MERGE preserva versoes de origem.
    sql=f"""MERGE `{TARGET}` T USING `{stage}` S
    ON T.id_registro=S.id_registro AND T.data_particao=S.data_particao
       AND T.data_particao BETWEEN @start AND @end
    WHEN NOT MATCHED THEN INSERT ({fields}) VALUES ({cols})"""
    conflitos=f"""SELECT COUNT(*) AS conflito FROM `{stage}` S
      JOIN `{TARGET}` T ON T.id_registro=S.id_registro
      AND T.data_particao=S.data_particao
      AND T.data_particao BETWEEN @start AND @end
      WHERE T.payload_sha256 != S.payload_sha256"""
    check=f"""SELECT COUNT(*) AS failed FROM `{stage}` S
      LEFT JOIN `{TARGET}` T ON T.id_registro=S.id_registro
      AND T.data_particao=S.data_particao AND T.data_particao BETWEEN @start AND @end
      WHERE T.id_registro IS NULL OR T.payload_sha256 != S.payload_sha256"""
    duplicate=f"""SELECT COUNT(*) AS duplicate_keys FROM (
      SELECT id_registro FROM `{TARGET}`
      WHERE data_particao BETWEEN @start AND @end
      AND id_registro IN (SELECT id_registro FROM `{stage}`)
      GROUP BY id_registro HAVING COUNT(*)>1)"""
    try:
        with arquivo.open("rb") as handle:
            client.load_table_from_file(handle,stage,job_config=cfg).result(timeout=180)
        tabela_tmp=client.get_table(stage)
        tabela_tmp.expires=datetime.now(timezone.utc)+timedelta(hours=6)
        client.update_table(tabela_tmp,["expires"])
        for statement in (sql,conflitos,check,duplicate):
            client.query(statement,job_config=qconf(True))
        divergencias=list(client.query(conflitos,job_config=qconf(False)).result(timeout=180))
        if len(divergencias)!=1 or int(divergencias[0]["conflito"])!=0:
            raise MigracaoBloqueada("CONFLITO_VINTAGE_ORIGEM: lote bloqueado antes do MERGE")
        client.query(sql,job_config=qconf(False)).result(timeout=180)
        invalid=list(client.query(check,job_config=qconf(False)).result(timeout=180))
        dupes=list(client.query(duplicate,job_config=qconf(False)).result(timeout=180))
        if len(invalid)!=1 or int(invalid[0]["failed"]) or len(dupes)!=1 or int(dupes[0]["duplicate_keys"]):
            raise MigracaoBloqueada("BIGQUERY_RECONCILIATION_FAILURE")
        return {**report,"status":"BIGQUERY_BATCH_VERIFICADO","gcp_written":True,
            "historical_cutover_approved":False}
    finally:
        client.delete_table(stage,not_found_ok=True)


def main(argv=None):
    p=argparse.ArgumentParser()
    p.add_argument("--dataset",choices=DATASETS)
    p.add_argument("--endpoint")
    p.add_argument("--arquivo",required=True,type=Path)
    p.add_argument("--carregar",action="store_true")
    p.add_argument("--validar",action="store_true")
    opts=p.parse_args(argv)
    try:
        if opts.dataset and opts.endpoint:
            summary=extrair(opts.dataset,opts.endpoint,_token(),opts.arquivo)
            if summary["rows"]==0:
                print(json.dumps(summary,ensure_ascii=False))
                return 0
        elif opts.validar or opts.carregar:
            summary=validar_arquivo(opts.arquivo)
        else:raise MigracaoBloqueada("INVALID_EXECUTION_MODE")
        if opts.carregar:summary=carregar_bigquery(opts.arquivo)
        print(json.dumps(summary,ensure_ascii=False,sort_keys=True))
        return 0
    except (MigracaoBloqueada,PermissionError,OSError,ValueError) as e:
        tag=str(e) if isinstance(e,(MigracaoBloqueada,PermissionError)) else type(e).__name__
        print("MIGRACAO_BLOQUEADA:"+tag,file=sys.stderr)
        return 3
if __name__=="__main__":raise SystemExit(main())
