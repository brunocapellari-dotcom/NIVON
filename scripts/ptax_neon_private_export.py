#!/usr/bin/env python3
"""Ponte Neon PTAX -> JSONL BigQuery: exportacao privada por OIDC GitHub.

- Somente leitura; nao provisiona nem consulta Google Cloud.
- Snapshot de id maximo no inicio limita o lote, mas nao e MVCC transacional.
- Em ciclos incrementais, reprocessar sobreposicao para capturar commits tardios.
- Todos os arquivos devem ficar fora do repositorio publico.
"""
from __future__ import annotations
import argparse
from collections import Counter
from datetime import date
from hashlib import sha256
import json
import os
from pathlib import Path
import re
import sys
from urllib.parse import urlencode, urlsplit
from urllib.request import Request, urlopen
from urllib.error import HTTPError
from typing import Callable, Any

from scripts.ptax_neon_to_bigquery_jsonl import normalize, InvalidQuote, SOURCE_FIELDS

ROOT=Path(__file__).resolve().parents[1]
AUDIENCE="urn:nivon:ptax:export:v1"
MAX_ROWS=100_000
PAGE_SIZE=100
MAX_ID=2**53-1

class PrivateExportError(ValueError):
    pass

def validated_endpoint(endpoint: str) -> str:
    u=urlsplit(endpoint)
    if (u.scheme!="https" or not u.hostname or not
        re.fullmatch(r"[a-z0-9-]+-ptaxbridge\.compute\.c-13\.us-east-1\.aws\.neon\.tech",u.hostname)
        or u.path not in ("","/") or u.query or u.fragment or u.port not in (None,443)
        or u.username or u.password):
        raise PrivateExportError("PTAX_ENDPOINT_NOT_APPROVED")
    return "https://"+u.hostname

def token_from_actions(opener: Callable = urlopen) -> str:
    token_url=os.getenv("ACTIONS_ID_TOKEN_REQUEST_URL","")
    request_token=os.getenv("ACTIONS_ID_TOKEN_REQUEST_TOKEN","")
    if not token_url.startswith("https://") or not request_token:
        raise PrivateExportError("GITHUB_OIDC_NOT_AVAILABLE")
    sep="&" if "?" in token_url else "?"
    u=token_url+sep+urlencode({"audience":AUDIENCE})
    with opener(Request(u,headers={"Authorization":"Bearer "+request_token}),timeout=20) as response:
        out=json.load(response)
    tok=out.get("value")
    if not isinstance(tok,str) or not 20<len(tok)<11000:
        raise PrivateExportError("INVALID_GITHUB_OIDC")
    return tok

def api_json(endpoint: str, token: str, path: str, query: dict[str,str], *,
             opener: Callable = urlopen) -> dict[str,Any]:
    u=endpoint+path+("?" + urlencode(query) if query else "")
    req=Request(u,headers={"Accept":"application/json","Authorization":"Bearer "+token,
                          "Cache-Control":"no-store"})
    with opener(req,timeout=45) as response:
        if response.status != 200:
            raise PrivateExportError("NEON_PRIVATE_API_BAD_STATUS")
        raw=response.read(750_001)
    if len(raw)>750_000:
        raise PrivateExportError("NEON_PRIVATE_API_OVERSIZE")
    out=json.loads(raw)
    if not isinstance(out,dict):
        raise PrivateExportError("NEON_PRIVATE_API_BAD_JSON")
    return out

def safe_id(v: Any, allow_zero: bool = False) -> int:
    if not isinstance(v,str) or not re.fullmatch(r"(?:0|[1-9][0-9]*)",v) or len(v)>16:
        raise PrivateExportError("PTAX_BAD_ID")
    n=int(v)
    if n>MAX_ID or (n==0 and not allow_zero):
        raise PrivateExportError("PTAX_ID_OUT_OF_RANGE")
    return n

def row_to_normalized(raw: dict[str,Any]) -> tuple[dict[str,Any],dict[str,Any]]:
    if not isinstance(raw,dict) or set(raw)!=SOURCE_FIELDS:
        raise PrivateExportError("PTAX_BAD_ROW_SCHEMA")
    item=dict(raw)
    item["id"]=safe_id(item["id"])
    try:
        mapped=normalize(item)
    except (InvalidQuote,ValueError,TypeError):
        raise PrivateExportError("PTAX_BAD_ROW") from None
    return item,mapped

def stream_pages(endpoint: str, token: str, after: int,
                 *, api: Callable = api_json, cap: int = MAX_ROWS):
    if type(after) is not int or not 0<=after<=MAX_ID or not 1<=cap<=MAX_ROWS:
        raise PrivateExportError("INVALID_EXPORT_BOUNDS")
    checkpoint=api(endpoint,token,"/checkpoint",{})
    if checkpoint.get("status")!="CHECKPOINT":
        raise PrivateExportError("INVALID_SOURCE_CHECKPOINT")
    upper=safe_id(checkpoint.get("upper_id"),allow_zero=True)
    count=checkpoint.get("row_count")
    if type(count) is not int or count<0 or count>1_000_000:
        raise PrivateExportError("INVALID_SOURCE_COUNT")
    if upper==0:
        if count!=0:raise PrivateExportError("SOURCE_CONSISTENCY_FAILURE")
        return upper, [],count
    if after>upper:
        raise PrivateExportError("CHECKPOINT_AHEAD_OF_SOURCE")
    pages=[]; n=0
    while after<upper:
        block=api(endpoint,token,"/export",{"after":str(after),"upto":str(upper),"limit":str(PAGE_SIZE)})
        if block.get("status")!="OK" or block.get("upper_id")!=str(upper) or block.get("after_id")!=str(after):
            raise PrivateExportError("BAD_CURSOR_PROTOCOL")
        rows=block.get("rows")
        if not isinstance(rows,list) or len(rows)>PAGE_SIZE or block.get("received")!=len(rows):
            raise PrivateExportError("BAD_PAGE_SHAPE")
        if not rows:break
        old=after
        for row in rows:
            if not isinstance(row,dict):raise PrivateExportError("BAD_ROW")
            rid=safe_id(row.get("id"))
            if rid<=after:
                # Somente IDs surrogate; nunca logar preco ou payload.
                raise PrivateExportError("UNORDERED_IDS_PREV_"+str(after)+"_CURRENT_"+str(rid))
            if rid>upper:
                raise PrivateExportError("ROW_ID_ABOVE_SNAPSHOT_UPPER")
            after=rid
        if block.get("next_after_id")!=str(after) or after==old:
            raise PrivateExportError("INVALID_NEXT_CURSOR")
        n+=len(rows)
        if n>cap:raise PrivateExportError("TOO_MANY_ROWS")
        pages.extend(rows)
        if len(rows)<PAGE_SIZE:break
    return upper,pages,count

def export(endpoint: str, source: Path, target: Path, *,
           after: int = 0, api: Callable = api_json, token: str = "") -> dict[str,Any]:
    endpoint=validated_endpoint(endpoint)
    if not token:raise PrivateExportError("TOKEN_REQUIRED")
    source=source.resolve()
    target=target.resolve()
    if source==target or source.is_relative_to(ROOT) or target.is_relative_to(ROOT):
        raise PrivateExportError("EXPORT_MUST_USE_PRIVATE_DIRECTORY")
    if source.exists() or target.exists():
        raise PrivateExportError("NO_OVERWRITE")
    upper, rows, source_count=stream_pages(endpoint,token,after,api=api)
    if not rows:raise PrivateExportError("EMPTY_SNAPSHOT_NOT_MIGRATED")
    source.parent.mkdir(parents=True,exist_ok=True,mode=0o700)
    target.parent.mkdir(parents=True,exist_ok=True,mode=0o700)
    handles=[]
    seen=set(); counts=Counter(); ref_ranges={}
    data_sha=sha256()
    try:
        for path in (source,target):
            handles.append(os.open(path,os.O_CREAT|os.O_EXCL|os.O_WRONLY,0o600))
        with os.fdopen(handles[0],"w",encoding="utf-8") as src, os.fdopen(handles[1],"w",encoding="utf-8") as dst:
            for obj in rows:
                raw,mapped=row_to_normalized(obj)
                if mapped["quote_id"] in seen:
                    raise PrivateExportError("DUPLICATE_QUOTE_KEY")
                seen.add(mapped["quote_id"])
                curr=mapped["currency"]
                counts[curr]+=1
                ref=mapped["reference_date"]
                if curr not in ref_ranges:ref_ranges[curr]=[ref,ref]
                else:ref_ranges[curr]=[min(ref,ref_ranges[curr][0]),max(ref,ref_ranges[curr][1])]
                src.write(json.dumps(raw,ensure_ascii=False,separators=(",",":"))+"\n")
                content=(json.dumps(mapped,ensure_ascii=False,separators=(",",":"))+"\n")
                dst.write(content)
                data_sha.update(content.encode("utf-8"))
    except BaseException:
        for fd in handles:
            try:os.close(fd)
            except OSError:pass
        source.unlink(missing_ok=True);target.unlink(missing_ok=True)
        raise
    return {"status":"PRIVATE_EXPORT_ONLY_NO_CLOUD_WRITE","source":"NEON_PTAX",
            "exported":len(rows),"source_checkpoint_upper_id":upper,"start_after_id":after,
            "source_count_at_checkpoint":source_count,
            "count_by_currency":dict(counts),"range_by_currency":ref_ranges,
            "target_jsonl_sha256":data_sha.hexdigest(),
            "transactional_snapshot":False,"gcp_loaded":False,"neon_job_modified":False,
            "next_gate":"RECONCILE_SOURCE_AND_AUTHORIZE_BIGQUERY"}

def main(argv=None)->int:
    p=argparse.ArgumentParser(description="PTAX: exportar lotes Neon OIDC para JSONL privado")
    p.add_argument("--endpoint",required=True)
    p.add_argument("--source-jsonl",required=True,type=Path)
    p.add_argument("--target-jsonl",required=True,type=Path)
    p.add_argument("--after-id",type=int,default=0)
    args=p.parse_args(argv)
    try:
        token=token_from_actions()
        result=export(args.endpoint,args.source_jsonl,args.target_jsonl,after=args.after_id,token=token)
    except HTTPError as exc:
        # Nunca imprimir URL, resposta, query, corpo ou token.
        # O erro pode ser 401/403 (OIDC/permissao), 429 (limite) ou 5xx (origem).
        status=exc.code if type(exc.code) is int and 100<=exc.code<=599 else 0
        print("PTAX_PRIVATE_EXPORT_FAILED:HTTP_"+str(status)+":NO_CLOUD_WRITE",
              file=sys.stderr)
        return 3
    except PrivateExportError as exc:
        # Apenas codigos internos constantes: nunca incluir token, URL ou preco.
        print("PTAX_PRIVATE_EXPORT_FAILED:"+str(exc)+":NO_CLOUD_WRITE",file=sys.stderr)
        return 3
    except (InvalidQuote,ValueError,OSError,UnicodeError) as exc:
        print("PTAX_PRIVATE_EXPORT_FAILED:"+type(exc).__name__+":NO_CLOUD_WRITE",file=sys.stderr)
        return 3
    print(json.dumps(result,ensure_ascii=False,sort_keys=True))
    return 0

if __name__=="__main__":raise SystemExit(main())
