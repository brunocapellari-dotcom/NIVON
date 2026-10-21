"""Manifest oficial FAOSTAT para coleta em lote planejada.

Acesso pontual, sem baixar ZIPs nem normalizar milhões de linhas.
Os arquivos fornecidos pelo manifest são metadados não confiáveis: o cliente
NUNCA segue FileLocation; downloads futuros exigirão aprovação por domínio.
"""
from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime, timezone
from urllib.parse import urlsplit
from urllib.request import Request, HTTPRedirectHandler, build_opener

MANIFEST = "https://bulks-faostat.fao.org/production/datasets_E.json"
DOMINIOS = frozenset({"QCL","RFB","RFM","PP","BE","TCL","TCLI"})
MAX_BYTES = 1_500_000


class ErroFAOBulk(ValueError):
    pass


class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def _instant(s):
    if not isinstance(s,str):
        raise ErroFAOBulk("data coleta ausente")
    try:
        dt=datetime.fromisoformat(s.replace("Z","+00:00"))
    except ValueError as exc:
        raise ErroFAOBulk("data coleta inválida") from exc
    if dt.tzinfo is None or dt.utcoffset() is None:
        raise ErroFAOBulk("coleta sem timezone")
    return dt.astimezone(timezone.utc).isoformat()


def _pairs(pairs):
    o={}
    for k,v in pairs:
        if k in o:
            raise ErroFAOBulk("chave JSON duplicada")
        o[k]=v
    return o


def normalizar_manifest(payload:bytes,*,coletado_em:str)->dict:
    coleta=_instant(coletado_em)
    if not isinstance(payload,bytes) or not 1<=len(payload)<=MAX_BYTES:
        raise ErroFAOBulk("payload ausente ou muito grande")
    try:
        raw=json.loads(payload.decode("utf-8-sig"),object_pairs_hook=_pairs)
    except (UnicodeError,json.JSONDecodeError) as exc:
        raise ErroFAOBulk("JSON inválido") from exc
    entry=raw.get("Datasets") if isinstance(raw,dict) else None
    dataset=entry.get("Dataset") if isinstance(entry,dict) else None
    if not isinstance(dataset,list) or not 1<=len(dataset)<=500:
        raise ErroFAOBulk("manifest não contém lista de datasets")
    out=[]
    ids=set()
    for x in dataset:
        if not isinstance(x,dict):
            raise ErroFAOBulk("dataset não é objeto")
        code=x.get("DatasetCode")
        if not isinstance(code,str) or not re.fullmatch(r"[A-Z]{1,8}",code) or code in ids:
            raise ErroFAOBulk("código duplicado ou inválido")
        ids.add(code)
        if code not in DOMINIOS:
            continue
        url=x.get("FileLocation")
        p=urlsplit(url) if isinstance(url,str) else None
        if (p is None or p.scheme!="https" or p.hostname!="bulks-faostat.fao.org"
                or not p.path.startswith("/production/") or not p.path.endswith(".zip")
                or ".." in p.path or p.query or p.fragment or p.username or p.password):
            raise ErroFAOBulk("endereço de arquivo inesperado")
        upd=x.get("DateUpdate")
        if not isinstance(upd,str) or not re.fullmatch(r"\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d",upd):
            raise ErroFAOBulk("atualização fonte inválida")
        rows=x.get("FileRows")
        if type(rows) is str and rows.isdigit():
            rows=int(rows)
        if type(rows) is not int or not 0<=rows<=100_000_000:
            raise ErroFAOBulk("contagem fonte inválida")
        size=x.get("FileSize")
        if not isinstance(size,str) or not re.fullmatch(r"\d{1,10}(?:KB|MB|GB)",size):
            raise ErroFAOBulk("tamanho arquivo desconhecido")
        if x.get("CompressionFormat")!="zip" or x.get("FileType")!="csv":
            raise ErroFAOBulk("formato arquivo incompatível")
        out.append({"dominio":code,
                    "nome_fonte":x.get("DatasetName"),
                    "data_atualizacao_dataset":upd,
                    "arquivo_zip_url_somente_referencia":url,
                    "tamanho_informado":size,"total_linhas_informado":rows,
                    "coleta":coleta,
                    "natureza":"CATALOGO_ARQUIVOS_FAOSTAT_NAO_OBSERVACAO_AGRICOLA"})
    if "QCL" not in [r["dominio"] for r in out]:
        raise ErroFAOBulk("domínio QCL canônico ausente")
    return {"dataset_id":"FAO_FAOSTAT_BULK_CATALOGO",
            "fonte_id":"FAO","consulta_url":MANIFEST,
            "total_dominios_manifest":len(dataset),"dominios_prioritarios":out,
            "total_prioritarios":len(out),"coleta":coleta,
            "publicacao_individual":None,
            "sha256_original":hashlib.sha256(payload).hexdigest(),
            "arquivos_grandes_baixados":False,
            "apto_publicacao_automatica":False,
            "estado":"MANIFEST_PUBLICO_PONTUAL_SEM_BACKFILL"}


def consultar_manifest(*,executar=False,abridor=None,instante=None):
    if executar is not True:
        raise PermissionError("FAOSTAT exige execução explícita, nenhuma chamada por padrão")
    dt=instante if instante is not None else datetime.now(timezone.utc)
    if not isinstance(dt,datetime) or dt.tzinfo is None or dt.utcoffset() is None:
        raise ErroFAOBulk("instante sem timezone")
    client=abridor if abridor is not None else build_opener(_NoRedirect())
    req=Request(MANIFEST,headers={"Accept":"application/json","User-Agent":"NIVON/0.1 (uso-nao-comercial)"})
    with client.open(req,timeout=20) as response:
        if int(response.status)!=200 or response.geturl()!=MANIFEST:
            raise ErroFAOBulk("HTTP/redirect inválido")
        mime=str(response.headers.get("Content-Type","")).split(";",1)[0].strip().lower()
        if mime!="application/json":
            raise ErroFAOBulk("MIME incompatível")
        b=response.read(MAX_BYTES+1)
        if len(b)>MAX_BYTES:
            raise ErroFAOBulk("manifest maior que limite")
    return normalizar_manifest(b,coletado_em=dt.isoformat())
