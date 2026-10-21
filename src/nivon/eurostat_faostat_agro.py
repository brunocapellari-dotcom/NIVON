"""Eurostat oilseeds area (JSON-stat) + FAOSTAT QCL crops (JSON) on demand.

No cron, storage, cost, tokens or automatic publication.
The official updated timestamp is dataset-vintage, NOT release time per row.
"""
from __future__ import annotations

import hashlib
import json
import math
import re
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from urllib.parse import urlencode, urlsplit
from urllib.request import Request, HTTPRedirectHandler, build_opener

EUROSTAT = "https://ec.europa.eu/eurostat/api/dissemination/statistics/1.0/data/tag00100"
FAOSTAT = "https://fenixservices.fao.org/faostat/api/v1/en/data/QCL"
COUNTRIES_EU = frozenset({"FR","DE","ES","PL","RO","IT","HU","NL","AT","EU27_2020"})
FAO_AREA = {"BRA": 21, "USA": 231, "ARG": 9}
FAO_ITEMS = {"SOJA": 236, "MILHO": 56, "TRIGO": 15}
MAX_SIZE = 1_500_000


class ErroEstatisticasAgro(ValueError):
    pass


class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def _coleta(s):
    if not isinstance(s, str):
        raise ErroEstatisticasAgro("carimbo de coleta ausente")
    try:
        t = datetime.fromisoformat(s.replace("Z", "+00:00"))
    except ValueError as e:
        raise ErroEstatisticasAgro("carimbo inválido") from e
    if t.tzinfo is None or t.utcoffset() is None:
        raise ErroEstatisticasAgro("coleta sem fuso")
    return t.astimezone(timezone.utc).isoformat()


def _unique(pairs):
    obj = {}
    for k,v in pairs:
        if k in obj:
            raise ErroEstatisticasAgro("JSON com chave duplicada")
        obj[k] = v
    return obj


def _json(payload):
    if not isinstance(payload, bytes) or not 1 <= len(payload) <= MAX_SIZE:
        raise ErroEstatisticasAgro("payload ausente ou excessivo")
    try:
        o = json.loads(payload.decode("utf-8-sig"), object_pairs_hook=_unique)
    except (UnicodeError, json.JSONDecodeError) as e:
        raise ErroEstatisticasAgro("JSON inválido") from e
    if not isinstance(o, dict):
        raise ErroEstatisticasAgro("documento deve ser objeto JSON")
    return o


def _decimal(x):
    if x is None:
        return None
    if type(x) not in (str, float, int):
        raise ErroEstatisticasAgro("indicador não numérico")
    try:
        v = Decimal(str(x))
    except InvalidOperation as e:
        raise ErroEstatisticasAgro("indicador não decimal") from e
    if not v.is_finite() or v < 0 or v > Decimal("100000000000000"):
        raise ErroEstatisticasAgro("indicador fora dos limites")
    return format(v, "f")


def planejar_eurostat(*, pais="FR", ano=2024):
    if pais not in COUNTRIES_EU or type(ano) is not int or not 2015 <= ano <= 2100:
        raise ErroEstatisticasAgro("país EU ou ano não permitido")
    return EUROSTAT + "?" + urlencode({"lang":"EN","geo":pais,"time":str(ano)})


def normalizar_eurostat(payload, *, pais, ano, coletado_em):
    url = planejar_eurostat(pais=pais, ano=ano)
    coleta = _coleta(coletado_em)
    doc = _json(payload)
    if doc.get("class") != "dataset" or not isinstance(doc.get("id"), list):
        raise ErroEstatisticasAgro("resposta não é JSON-stat dataset")
    dims = doc["id"]
    sizes = doc.get("size")
    if (len(dims) != len(set(dims)) or not 1 <= len(dims) <= 8
            or not isinstance(sizes, list) or len(sizes) != len(dims)
            or any(type(n) is not int or n < 1 or n > 100 for n in sizes)):
        raise ErroEstatisticasAgro("dimensões JSON-stat inválidas")
    length = math.prod(sizes)
    if length > 200:
        raise ErroEstatisticasAgro("cubo maior que consulta restrita")
    if not {"geo", "time", "crops", "strucpro"} <= set(dims):
        raise ErroEstatisticasAgro("dimensões esperadas não presentes")
    dim = doc.get("dimension")
    if not isinstance(dim, dict):
        raise ErroEstatisticasAgro("metadados de dimensões ausentes")
    labels = {}
    for name, n in zip(dims, sizes):
        meta = dim.get(name)
        cat = meta.get("category") if isinstance(meta, dict) else None
        index = cat.get("index") if isinstance(cat, dict) else None
        if not isinstance(index, dict) or len(index) != n:
            raise ErroEstatisticasAgro("índices de dimensão incompletos")
        codes = [None] * n
        for code, position in index.items():
            if not isinstance(code, str) or type(position) is not int or not 0 <= position < n or codes[position] is not None:
                raise ErroEstatisticasAgro("índice de categoria inválido")
            codes[position] = code
        labels[name] = codes
    if labels["geo"] != [pais] or labels["time"] != [str(ano)]:
        raise ErroEstatisticasAgro("país/ano divergente da consulta")
    if any(x != "AR_THS_HA" for x in labels["strucpro"]):
        raise ErroEstatisticasAgro("unidade Eurostat não é mil hectares")
    if labels.get("freq") not in (None, ["A"]):
        raise ErroEstatisticasAgro("frequência não anual")
    data = doc.get("value", {})
    status = doc.get("status", {})
    if not isinstance(data, (dict, list)) or not isinstance(status, (dict, list)):
        raise ErroEstatisticasAgro("matrizes value/status inválidas")
    if isinstance(data, list) and len(data) != length:
        raise ErroEstatisticasAgro("lista value desalinhada")
    if isinstance(status, list) and len(status) != length:
        raise ErroEstatisticasAgro("lista status desalinhada")
    if isinstance(data, dict) and any(not str(k).isdigit() or not 0 <= int(k) < length for k in data):
        raise ErroEstatisticasAgro("índices value fora do cubo")
    out=[]
    for flat in range(length):
        val = data[flat] if isinstance(data, list) else data.get(str(flat))
        if val is None:
            continue
        pos=[]; rem=flat
        for n in reversed(sizes):
            pos.append(rem % n); rem //= n
        positions=list(reversed(pos))
        axes={k:labels[k][index] for k,index in zip(dims,positions)}
        flags=(status[flat] if isinstance(status,list) else status.get(str(flat)))
        if flags is not None and not isinstance(flags,str):
            raise ErroEstatisticasAgro("flag de qualidade inválida")
        out.append({
            "pais":pais,"ano_referencia":str(ano),"competencia":str(ano),
            "cultura_codigo":axes["crops"], "estrutura_codigo":axes["strucpro"],
            "valor_mil_ha":_decimal(val),"unidade":"MIL_HECTARES",
            "indicador":"AREA_CULTIVADA_OLEAGINOSAS",
            "flag_fonte":flags,"natureza":"ESTATISTICA_EUROSTAT_NAO_SAFRA_BRASIL",
            "publicacao":None,"coleta":coleta,
        })
    return {"dataset_id":"EUROSTAT_OLEAGINOSAS_AREA",
            "fonte_id":"EUROSTAT","consulta_url":url,"observacoes":out,
            "numero_observacoes":len(out),
            "updated_dataset_fonte":doc.get("updated"),
            "publicacao_individual":None,"coleta":coleta,
            "sha256_original":hashlib.sha256(payload).hexdigest(),
            "apto_publicacao_automatica":False,
            "estado":"NORMALIZADO_PONTUAL_SEM_VINTAGE_HISTORICO"}


def planejar_faostat(*, pais="BRA", cultura="SOJA", ano=2023):
    if pais not in FAO_AREA or cultura not in FAO_ITEMS or type(ano) is not int or not 1961 <= ano <= 2100:
        raise ErroEstatisticasAgro("consulta FAO fora do recorte")
    params={"area":FAO_AREA[pais],"item":FAO_ITEMS[cultura],
            "element":5510,"year":ano,"show_code":1,"show_unit":1,
            "show_flags":1,"null_values":0,"limit":50,"output_type":"objects"}
    return FAOSTAT+"?"+urlencode(params)


def normalizar_faostat(payload, *, pais, cultura, ano, coletado_em):
    url=planejar_faostat(pais=pais,cultura=cultura,ano=ano)
    coleta=_coleta(coletado_em)
    doc=_json(payload)
    rows=doc.get("data")
    if not isinstance(rows,list):
        raise ErroEstatisticasAgro("FAOSTAT sem data[]")
    # FAOSTAT v1 has historically exposed either a list of dicts or a
    # tabular header row followed by arrays. Both forms need strict shape.
    if rows and isinstance(rows[0],list):
        header=rows[0]
        if (not header or any(not isinstance(x,str) for x in header)
                or len(header)!=len(set(header)) or len(header)>80):
            raise ErroEstatisticasAgro("header FAO inválido")
        tab=[]
        for row in rows[1:]:
            if not isinstance(row,list) or len(row)!=len(header):
                raise ErroEstatisticasAgro("linha FAO desalinhada")
            tab.append(dict(zip(header,row)))
        rows=tab
    if len(rows)>50:
        raise ErroEstatisticasAgro("mais de 50 registros fora do recorte")
    normalized=[]
    for x in rows:
        if not isinstance(x,dict):
            raise ErroEstatisticasAgro("item FAO não é objeto")
        def first(*fields):
            for key in fields:
                if key in x and x[key] not in (None,""):
                    return x[key]
            return None
        area=first("Area Code","Area Code (FAO)","area_code")
        item=first("Item Code","Item Code (CPC)","item_code")
        element=first("Element Code","element_code")
        yr=first("Year","year")
        # If API omits any of the codes, do not accept silent mismatch.
        if (str(area)!=str(FAO_AREA[pais]) or str(item)!=str(FAO_ITEMS[cultura])
                or str(element)!="5510" or str(yr)!=str(ano)):
            raise ErroEstatisticasAgro("FAOSTAT códigos de área/cultura/elemento/ano divergentes")
        unit=first("Unit","unit")
        if not isinstance(unit,str) or not 1<=len(unit)<=35:
            raise ErroEstatisticasAgro("unidade de produção FAO ausente")
        normalized.append({
            "pais":pais,"cultura":cultura,
            "ano_referencia":str(ano),"competencia":str(ano),
            "elemento_fonte":"5510",
            "valor_original":_decimal(first("Value","value")),
            "unidade_original":unit,
            "flag_fonte":first("Flag","flag"),
            "nota_fonte":first("Note","note"),
            "natureza":"ESTATISTICA_FAOSTAT_PRODUCAO_NAO_ESTIMATIVA_SAFRA_CONAB",
            "publicacao":None,"coleta":coleta
        })
    if not normalized:
        raise ErroEstatisticasAgro("FAOSTAT retornou nenhuma observação verificada")
    return {"dataset_id":"FAO_FAOSTAT_LONG_RUN","fonte_id":"FAO",
            "consulta_url":url,"observacoes":normalized,
            "numero_observacoes":len(normalized),"coleta":coleta,
            "sha256_original":hashlib.sha256(payload).hexdigest(),
            "publicacao_individual":None,"apto_publicacao_automatica":False,
            "estado":"PRODUCAO_FAOSTAT_PONTUAL_NAO_PERSISTIDA"}


def _http(url, *, source, executar=False, abridor=None, instante=None):
    if executar is not True:
        raise PermissionError("consultas externas bloqueadas sem executar=True")
    p=urlsplit(url)
    allowed={
        "eurostat":("ec.europa.eu","/eurostat/api/dissemination/statistics/1.0/data/tag00100"),
        "faostat":("fenixservices.fao.org","/faostat/api/v1/en/data/QCL")
    }
    host, path=allowed[source]
    if (p.scheme!="https" or p.hostname!=host or p.path!=path or not p.query or
            p.username or p.password or p.fragment or p.port not in (None,443)):
        raise ErroEstatisticasAgro("domínio/recurso não autorizado")
    now=instante or datetime.now(timezone.utc)
    stamp=_coleta(now.isoformat())
    client=abridor if abridor is not None else build_opener(_NoRedirect())
    req=Request(url,headers={"Accept":"application/json","User-Agent":"NIVON/0.1 (pesquisa nao comercial)"})
    with client.open(req,timeout=20) as response:
        if int(response.status)!=200 or response.geturl()!=url:
            raise ErroEstatisticasAgro("HTTP/redirect recusado")
        mime=str(response.headers.get("Content-Type","")).split(";",1)[0].strip().lower()
        if mime not in ("application/json","application/json-stat","application/vnd.sdmx.data+json"):
            raise ErroEstatisticasAgro("MIME de estatística incompatível")
        b=response.read(MAX_SIZE+1)
        if not 1<=len(b)<=MAX_SIZE:
            raise ErroEstatisticasAgro("resposta vazia/acima do limite")
    return b,stamp


def consultar_eurostat(*,pais="FR",ano=2024,executar=False,abridor=None,instante=None):
    url=planejar_eurostat(pais=pais,ano=ano)
    raw,coleta=_http(url,source="eurostat",executar=executar,abridor=abridor,instante=instante)
    return normalizar_eurostat(raw,pais=pais,ano=ano,coletado_em=coleta)


def consultar_faostat(*,pais="BRA",cultura="SOJA",ano=2023,executar=False,abridor=None,instante=None):
    url=planejar_faostat(pais=pais,cultura=cultura,ano=ano)
    raw,coleta=_http(url,source="faostat",executar=executar,abridor=abridor,instante=instante)
    return normalizar_faostat(raw,pais=pais,cultura=cultura,ano=ano,coletado_em=coleta)
