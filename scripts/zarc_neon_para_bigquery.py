#!/usr/bin/env python3
"""NIVON: copia ZARC MT do Neon AGRO-DADOS ao BigQuery em staging privado.

Nao promove risco agronomico, nao modifica Neon, nao apaga linhas.
Pede uma connection string temporaria com SSL fornecida pelo administrador do Neon,
por variavel NIVON_ZARC_NEON_DSN (no GitHub Secrets) ou prompt oculto.
"""
from __future__ import annotations
import argparse
from datetime import date, datetime, timezone
from decimal import Decimal
from getpass import getpass
from hashlib import sha256
import json
import os
from pathlib import Path
import re
import sys
from typing import Any

TARGET="nivon-data.nivon_stage.zarc_linhas_mt"
ROOT=Path(__file__).resolve().parents[1]
MAX_LINES=250_000
MAX_BYTES=150_000_000
MAX_BYTES_BILLED=1_073_741_824
FIELDS=("source_sha256","linha_fisica","municipio_ibge","chave_logica_sha",
"conteudo_sha","payload_json","payload_sha256","data_particao","data_referencia",
"data_publicacao","data_coleta","competencia","direitos_revisados",
"dados_agronomicos_homologados","raw_backup_verificado","apto_modelo","tipo_coleta")


class ZarcBloqueado(ValueError):
    pass


def canonical(o:Any)->Any:
    if isinstance(o,Decimal):
        if not o.is_finite():raise ZarcBloqueado("INVALID_DECIMAL")
        return format(o,"f")
    if isinstance(o,dict):return {str(k):canonical(v) for k,v in o.items()}
    if isinstance(o,list):return [canonical(v) for v in o]
    if isinstance(o,(bool,str,int)) or o is None:return o
    raise ZarcBloqueado("INVALID_RAW_VALUE")


def _d(s:Any)->str | None:
    if s is None:return None
    if not isinstance(s,str) or len(s)<10:raise ZarcBloqueado("INVALID_DATE")
    try:
        x=date.fromisoformat(s[:10])
        return x.isoformat() if s[:10]==x.isoformat() else None
    except ValueError:
        raise ZarcBloqueado("INVALID_DATE") from None


def _t(s:Any)->str:
    if not isinstance(s,str):raise ZarcBloqueado("TIME_MISSING")
    try:
        t=datetime.fromisoformat(s.replace("Z","+00:00"))
        if t.utcoffset() is None:raise ValueError
        return t.astimezone(timezone.utc).isoformat().replace("+00:00","Z")
    except ValueError:raise ZarcBloqueado("TIME_INVALID") from None


def normalizar(origem:dict)->dict:
    if not isinstance(origem,dict):raise ZarcBloqueado("SOURCE_NOT_OBJECT")
    try:
        sha=str(origem["source_sha256"]).strip()
        linha=int(origem["linha_fisica"])
        ibge=str(origem["municipio_ibge"]).strip()
        logical=str(origem["chave_logica_sha"]).strip()
        content=str(origem["conteudo_sha"]).strip()
        raw=origem["payload_json"]
    except (ValueError,TypeError,KeyError):raise ZarcBloqueado("SOURCE_FIELDS_INVALID") from None
    if not re.fullmatch(r"[a-f0-9]{64}",sha) or        not re.fullmatch(r"[a-f0-9]{64}",logical) or        not re.fullmatch(r"[a-f0-9]{64}",content) or        not re.fullmatch(r"[0-9]{7}",ibge) or not 1<=linha<10**10:
        raise ZarcBloqueado("ZARC_IDENTITY_INVALID")
    if not isinstance(raw,str) or len(raw)>500_000:raise ZarcBloqueado("RAW_TOO_LARGE")
    try:
        payload=canonical(json.loads(raw,parse_float=Decimal))
    except (ValueError,TypeError):raise ZarcBloqueado("RAW_INVALID") from None
    if not isinstance(payload,dict):raise ZarcBloqueado("RAW_OBJECT_REQUIRED")
    if payload.get("source_sha256")!=sha or payload.get("linha_fisica")!=linha:
        raise ZarcBloqueado("RAW_SOURCE_ID_MISMATCH")
    text=json.dumps(payload,ensure_ascii=False,sort_keys=True,separators=(",",":"))
    ref=_d(origem.get("data_referencia"))
    pub=_d(origem.get("data_publicacao"))
    collected=_t(origem.get("data_coleta"))
    competence=origem.get("competencia")
    if not isinstance(competence,str) or not competence or len(competence)>80:
        raise ZarcBloqueado("ZARC_COMPETENCIA_INVALIDA")
    # Reproduzir exatamente flags de governanca. Nao promocionar dados.
    for key in ("direitos_revisados","dados_agronomicos_homologados","raw_backup_verificado"):
        if type(origem.get(key)) is not bool:raise ZarcBloqueado("MISSING_QA_FLAG")
    if origem.get("tipo_coleta") not in ("REAL_AUTORIZADO","SINTETICO"):
        raise ZarcBloqueado("COLLECTION_TYPE_INVALID")
    return {
      "source_sha256":sha,"linha_fisica":linha,"municipio_ibge":ibge,
      "chave_logica_sha":logical,"conteudo_sha":content,
      "payload_json":text,"payload_sha256":sha256(text.encode()).hexdigest(),
      "data_particao":ref or pub or collected[:10],
      "data_referencia":ref,"data_publicacao":pub,
      "data_coleta":collected,"competencia":competence,
      "direitos_revisados":origem["direitos_revisados"],
      "dados_agronomicos_homologados":origem["dados_agronomicos_homologados"],
      "raw_backup_verificado":origem["raw_backup_verificado"],
      "apto_modelo":False,
      "tipo_coleta":origem["tipo_coleta"]}


SQL_COUNT="""SELECT COUNT(*) FROM nivon_agro_staging.zarc_linhas_mt"""
SQL_SOURCE="""SELECT
l.source_sha256::text AS source_sha256,l.linha_fisica,
l.municipio_ibge::text AS municipio_ibge,l.chave_logica_sha::text AS chave_logica_sha,
l.conteudo_sha::text AS conteudo_sha,to_jsonb(l)::text AS payload_json,
e.data_referencia::text AS data_referencia,e.data_publicacao::text AS data_publicacao,
e.criado_em::text AS data_coleta,e.competencia,e.direitos_revisados,
e.dados_agronomicos_homologados,e.raw_backup_verificado,
CASE WHEN EXISTS(SELECT 1 FROM nivon_agro_staging.zarc_coletas c
                WHERE c.source_sha256=e.source_sha256
                  AND c.tipo='REAL_AUTORIZADO')
     THEN 'REAL_AUTORIZADO' ELSE 'SINTETICO' END AS tipo_coleta
FROM nivon_agro_staging.zarc_linhas_mt l
JOIN nivon_agro_staging.zarc_edicoes e ON l.source_sha256=e.source_sha256
ORDER BY l.source_sha256,l.linha_fisica"""


def extrair(dsn:str,arquivo:Path)->dict:
    if not isinstance(dsn,str) or not dsn.strip():raise ZarcBloqueado("DSN_NOT_PROVIDED")
    if arquivo.is_symlink() or arquivo.exists() or arquivo.resolve().is_relative_to(ROOT):
        raise ZarcBloqueado("PRIVATE_OUTPUT_REQUIRED")
    try:import psycopg
    except ImportError:raise ZarcBloqueado("PSYCOPG_NOT_INSTALLED") from None
    arquivo.parent.mkdir(parents=True,exist_ok=True,mode=0o700)
    size=0;count=0;ids=set();hashdata=sha256()
    try:
        with psycopg.connect(dsn,connect_timeout=15) as conn:
            with conn.transaction():
                conn.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY")
                expect=conn.execute(SQL_COUNT).fetchone()[0]
                if expect<=0 or expect>MAX_LINES:raise ZarcBloqueado("UNEXPECTED_SOURCE_COUNT")
                from psycopg.rows import dict_row
                with conn.cursor(name="zarc_nivon_export",row_factory=dict_row) as cur:
                    cur.execute(SQL_SOURCE)
                    with arquivo.open("x",encoding="utf-8") as out:
                        os.chmod(arquivo,0o600)
                        for line in cur:
                            result=normalizar(line)
                            key=(result["source_sha256"],result["linha_fisica"])
                            if key in ids:raise ZarcBloqueado("SOURCE_DUPLICATE_ROW")
                            ids.add(key)
                            raw=(json.dumps(result,ensure_ascii=False,separators=(",",":"))+"\n").encode()
                            size+=len(raw)
                            count+=1
                            if size>MAX_BYTES or count>MAX_LINES:
                                raise ZarcBloqueado("SOURCE_EXPORT_LIMIT")
                            hashdata.update(raw)
                            out.write(raw.decode())
                if count!=expect:raise ZarcBloqueado("SOURCE_SNAPSHOT_COUNT_MISMATCH")
    except BaseException:
        arquivo.unlink(missing_ok=True)
        raise
    return {"status":"ZARC_PRIVATE_EXPORT_ONLY","linhas":count,
      "sha256":hashdata.hexdigest(),"bytes":size,
      "bigquery_loaded":False,"apto_modelo":False,"neon_unchanged":True}


def plano(path:Path)->dict:
    if path.is_symlink() or not path.is_file() or path.resolve().is_relative_to(ROOT):
        raise ZarcBloqueado("UNSAFE_SOURCE_FILE")
    st=path.stat()
    if st.st_mode&0o077 or not 0<st.st_size<=MAX_BYTES:
        raise ZarcBloqueado("UNSAFE_SOURCE_PERMISSIONS_OR_SIZE")
    n=0;first=None;last=None;hashdata=sha256();ids=set()
    with path.open("rb") as f:
        for raw in f:
            n+=1
            if n>MAX_LINES:raise ZarcBloqueado("FILE_TOO_MANY_ROWS")
            hashdata.update(raw)
            try:r=json.loads(raw)
            except ValueError:raise ZarcBloqueado("INVALID_BIGQUERY_JSON") from None
            if set(r)!=set(FIELDS) or r["apto_modelo"] is not False:
                raise ZarcBloqueado("BAD_ZARC_SCHEMA_OR_PROMOTION")
            key=(r["source_sha256"],r["linha_fisica"])
            if key in ids:raise ZarcBloqueado("DUPLICATED_SOURCE_KEY")
            ids.add(key)
            if sha256(r["payload_json"].encode()).hexdigest()!=r["payload_sha256"]:
                raise ZarcBloqueado("PAYLOAD_HASH_MISMATCH")
            d=_d(r["data_particao"])
            first=min(first,d) if first else d;last=max(last,d) if last else d
    if n==0:raise ZarcBloqueado("ZARC_EMPTY_FILE")
    return {"rows":n,"min_date":first,"max_date":last,
        "sha256":hashdata.hexdigest(),"target":TARGET,"cloud_written":False,
        "agronomic_homologation":False}


def carregar(path:Path)->dict:
    p=plano(path)
    if os.getenv("NIVON_GCP_WRITE_APPROVED")!="true" or os.getenv("NIVON_GCP_COST_REVIEWED")!="true":
        raise PermissionError("GCP_NOT_APPROVED")
    from google.cloud import bigquery
    from uuid import uuid4
    cli=bigquery.Client(project="nivon-data")
    dest=cli.get_table(TARGET)
    if not dest.time_partitioning or dest.time_partitioning.field!="data_particao" or        not dest.require_partition_filter or set(f.name for f in dest.schema)!=set(FIELDS):
        raise ZarcBloqueado("ZARC_SCHEMA_GCP_INCOMPATIBLE")
    temp="nivon-data.nivon_stage._zarc_import_"+uuid4().hex[:18]
    cfg=bigquery.LoadJobConfig(schema=dest.schema,
         source_format=bigquery.SourceFormat.NEWLINE_DELIMITED_JSON,
         write_disposition=bigquery.WriteDisposition.WRITE_EMPTY)
    pars=[bigquery.ScalarQueryParameter("start","DATE",p["min_date"]),
          bigquery.ScalarQueryParameter("end","DATE",p["max_date"])]
    conf=lambda dry:bigquery.QueryJobConfig(
        query_parameters=pars,dry_run=dry,maximum_bytes_billed=MAX_BYTES_BILLED)
    columns=",".join(FIELDS)
    fields=",".join("S."+f for f in FIELDS)
    merge=f"""MERGE `{TARGET}` T USING `{temp}` S ON
      T.source_sha256=S.source_sha256 AND T.linha_fisica=S.linha_fisica
      AND T.data_particao=S.data_particao AND T.data_particao BETWEEN @start AND @end
      WHEN NOT MATCHED THEN INSERT ({columns}) VALUES ({fields})"""
    check=f"""SELECT COUNT(*) AS errors FROM `{temp}` S
      LEFT JOIN `{TARGET}` T ON T.source_sha256=S.source_sha256
      AND T.linha_fisica=S.linha_fisica AND T.data_particao=S.data_particao
      AND T.data_particao BETWEEN @start AND @end
      WHERE T.source_sha256 IS NULL OR T.payload_sha256!=S.payload_sha256"""
    duplicate=f"""SELECT COUNT(*) AS duplicates FROM (
      SELECT source_sha256,linha_fisica FROM `{TARGET}`
      WHERE data_particao BETWEEN @start AND @end
      GROUP BY source_sha256,linha_fisica HAVING COUNT(*)>1)"""
    try:
        with path.open("rb") as fd:
            cli.load_table_from_file(fd,temp,job_config=cfg).result(timeout=600)
        for stmt in (merge,check,duplicate):
            cli.query(stmt,job_config=conf(True))
        cli.query(merge,job_config=conf(False)).result(timeout=600)
        errors=list(cli.query(check,job_config=conf(False)).result(timeout=600))
        dupes=list(cli.query(duplicate,job_config=conf(False)).result(timeout=600))
        if len(errors)!=1 or errors[0]["errors"] or len(dupes)!=1 or dupes[0]["duplicates"]:
            raise ZarcBloqueado("ZARC_BIGQUERY_RECONCILIATION_FAILED")
        return {**p,"cloud_written":True,"status":"ZARC_BIGQUERY_VERIFIED",
          "agronomic_homologation":False}
    finally:
        cli.delete_table(temp,not_found_ok=True)


def main(argv=None):
    ap=argparse.ArgumentParser()
    ap.add_argument("--arquivo",required=True,type=Path)
    ap.add_argument("--extrair",action="store_true")
    ap.add_argument("--carregar",action="store_true")
    args=ap.parse_args(argv)
    try:
        if args.extrair:
            dsn=os.getenv("NIVON_ZARC_NEON_DSN") or getpass("DSN privado Neon AGRO-DADOS: ")
            print(json.dumps(extrair(dsn,args.arquivo),ensure_ascii=False))
        if not args.extrair or args.carregar:
            result=carregar(args.arquivo) if args.carregar else plano(args.arquivo)
            print(json.dumps(result,ensure_ascii=False))
        return 0
    except (ZarcBloqueado,PermissionError,OSError) as e:
        key=str(e) if isinstance(e,(ZarcBloqueado,PermissionError)) else type(e).__name__
        print("ZARC_MIGRACAO_BLOQUEADA:"+key,file=sys.stderr)
        return 3
if __name__=="__main__":raise SystemExit(main())
