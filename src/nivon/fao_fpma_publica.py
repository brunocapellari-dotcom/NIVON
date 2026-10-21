"""FAO GIEWS FPMA: catálogo e cotações oficiais internacionais/domésticas.

GET público sem credencial, uma página/UUID por chamada; não confundir com
CEPEA/IMEA, preço na origem do Brasil ou futures da CBOT. Moeda e unidade
são características da série selecionada, nunca presumidas ou convertidas.
"""
from __future__ import annotations
import hashlib
import json
import math
import re
import uuid
from datetime import date, datetime, timezone
from urllib.parse import urlencode
from .apis_gratuitas_execucao import _obter_json


BASE = "https://fpma.fao.org/giews/v4/global/price_module/api/v1/"
PAISES = frozenset({"BRA","ARG","USA","CHN","IND","ZAF","KEN","IDN","VNM","UKR"})
PERIODICIDADES = frozenset({"daily","weekly","monthly"})


class ErroFAOFPMA(ValueError):
    pass


def _json(payload):
    if not isinstance(payload,bytes) or not 1<=len(payload)<=800_000:
        raise ErroFAOFPMA("resposta vazia ou grande demais")
    def unicos(pairs):
        o={}
        for k,v in pairs:
            if k in o:
                raise ErroFAOFPMA("chave JSON duplicada")
            o[k]=v
        return o
    try:
        o=json.loads(payload.decode("utf-8-sig"),object_pairs_hook=unicos)
    except (UnicodeError,json.JSONDecodeError) as exc:
        raise ErroFAOFPMA("JSON FAO inválido") from exc
    if not isinstance(o,dict) or not isinstance(o.get("results"),list):
        raise ErroFAOFPMA("API FPMA sem results[]")
    if type(o.get("count")) is not int or o["count"]<len(o["results"]):
        raise ErroFAOFPMA("count incompatível")
    if len(o["results"])>200:
        raise ErroFAOFPMA("uma página excedeu 200 resultados")
    return o


def _coleta(valor):
    if not isinstance(valor,str):
        raise ErroFAOFPMA("coleta inválida")
    try:
        d=datetime.fromisoformat(valor.replace("Z","+00:00"))
    except ValueError as exc:
        raise ErroFAOFPMA("coleta inválida") from exc
    if d.tzinfo is None or d.utcoffset() is None:
        raise ErroFAOFPMA("coleta sem fuso")
    return d.astimezone(timezone.utc).isoformat()


def _uuid(s):
    if not isinstance(s,str):
        raise ErroFAOFPMA("UUID ausente")
    try:
        uid=uuid.UUID(s)
    except (ValueError,AttributeError) as exc:
        raise ErroFAOFPMA("UUID inválido") from exc
    if str(uid)!=s.lower():
        raise ErroFAOFPMA("UUID precisa ser canônico")
    return str(uid)


def planejar_catalogo(*,pais="BRA",pagina=1):
    if pais not in PAISES or type(pagina) is not int or not 1<=pagina<=5:
        raise ErroFAOFPMA("país/página fora da janela")
    return BASE+"FpmaSerie/?" + urlencode({"iso3_country_codes":pais,"page":pagina})


def normalizar_catalogo(payload,*,pais,pagina,coletado_em):
    url=planejar_catalogo(pais=pais,pagina=pagina)
    o=_json(payload); coleta=_coleta(coletado_em)
    itens=[]; ids=set()
    for x in o["results"]:
        if not isinstance(x,dict):
            raise ErroFAOFPMA("série FAO não é objeto")
        ident=_uuid(x.get("uuid"))
        if ident in ids:
            raise ErroFAOFPMA("UUID repetido")
        ids.add(ident)
        # Metadados são preservados como metadados, não informação numérica atual.
        itens.append({"uuid":ident, "pais_consultado":pais,
            "commodity_original":x.get("commodity"),
            "tipo_preco_original":x.get("price_type"),
            "moeda_metadado":x.get("currency"),
            "unidade_metadado":x.get("measure_unit_label"),
            "periodicidades_disponiveis":x.get("periodicities"),
            "natureza":"METADADOS_DE_SERIE_FAO_NAO_PRECO",
            "coleta":coleta})
    return {"dataset_id":"FAO_FPMA_SERIES_CATALOGO","fonte_id":"FAO",
        "consulta_url":url,"series":itens,"quantidade":len(itens),
        "count_total_fonte":o["count"],"proxima_pagina_disponivel":o.get("next") is not None,
        "paginacao_completa":o.get("next") is None,"coleta":coleta,
        "sha256_original":hashlib.sha256(payload).hexdigest(),
        "apto_publicacao_automatica":False,"estado":"METADADOS_PONTUAIS_SEM_ATIVACAO"}


def consultar_catalogo(*,pais="BRA",pagina=1,executar=False,abridor=None,instante=None):
    url=planejar_catalogo(pais=pais,pagina=pagina)
    raw=_obter_json(url,recurso="fao_fpma_catalog",executar=executar,abridor=abridor,instante=instante)
    dados=normalizar_catalogo(raw["bytes"],pais=pais,pagina=pagina,coletado_em=raw["coleta"])
    return {"aquisicao":{k:v for k,v in raw.items() if k!="bytes"},"dados":dados}


def planejar_precos(*,serie_uuid,periodicidade="monthly"):
    ident=_uuid(serie_uuid)
    if periodicidade not in PERIODICIDADES:
        raise ErroFAOFPMA("periodicidade desconhecida")
    return BASE+"FpmaSeriePrice/?" + urlencode({"uuid__in":ident,"periodicity":periodicidade})


def _decimal(v):
    if v is None:
        return None
    if type(v) not in (str,int,float):
        raise ErroFAOFPMA("preço não decimal")
    try:
        from decimal import Decimal
        d=Decimal(str(v))
    except Exception as exc:
        raise ErroFAOFPMA("preço malformado") from exc
    if not d.is_finite() or d<0 or d>1e12:
        raise ErroFAOFPMA("preço fora de limite")
    return format(d,"f")


def normalizar_precos(payload,*,serie_uuid,periodicidade,coletado_em):
    url=planejar_precos(serie_uuid=serie_uuid,periodicidade=periodicidade)
    doc=_json(payload); coleta=_coleta(coletado_em); itens=[]; seen=set()
    for ser in doc["results"]:
        if not isinstance(ser,dict) or _uuid(ser.get("uuid"))!=_uuid(serie_uuid):
            raise ErroFAOFPMA("série inesperada")
        pts=ser.get("datapoints")
        if not isinstance(pts,list) or len(pts)>10_000:
            raise ErroFAOFPMA("datapoints ausentes/excessivos")
        for x in pts:
            if not isinstance(x,dict) or x.get("periodicity")!=periodicidade:
                raise ErroFAOFPMA("periodicidade divergente")
            data=x.get("date")
            try:
                d=date.fromisoformat(data)
            except (TypeError,ValueError) as exc:
                raise ErroFAOFPMA("data preço inválida") from exc
            if d.isoformat() in seen:
                raise ErroFAOFPMA("data duplicada")
            seen.add(d.isoformat())
            itens.append({"uuid":serie_uuid,"data_referencia":d.isoformat(),
                "competencia":d.strftime("%Y-%m"),"periodicidade":periodicidade,
                "valor_original":_decimal(x.get("price_value")),
                "valor_real_fonte":_decimal(x.get("price_value_real")),
                "valor_usd_fonte":_decimal(x.get("price_value_dollar")),
                "fator_conversao_fonte":_decimal(x.get("conversion_factor")),
                "moeda_e_unidade":None,"publicacao":None,"coleta":coleta,
                "natureza":"PRECO_ORIGINAL_FAO_ORIGEM_NAO_CEPEA_IMEA"})
    return {"dataset_id":"FAO_FPMA_PRECOS_SERIES","fonte_id":"FAO",
        "serie_uuid":serie_uuid,"consulta_url":url,"observacoes":itens,"quantidade":len(itens),
        "paginacao_completa":doc.get("next") is None,
        "coleta":coleta,"sha256_original":hashlib.sha256(payload).hexdigest(),
        "dados_sem_metadados_unidade":True,"apto_publicacao_automatica":False,
        "estado":"PRECOS_PONTUAIS_PRECISAM_CROSSWALK_SERIE"}


def consultar_precos(*,serie_uuid,periodicidade="monthly",executar=False,abridor=None,instante=None):
    url=planejar_precos(serie_uuid=serie_uuid,periodicidade=periodicidade)
    raw=_obter_json(url,recurso="fao_fpma_prices",executar=executar,abridor=abridor,instante=instante)
    dados=normalizar_precos(raw["bytes"],serie_uuid=serie_uuid,periodicidade=periodicidade,coletado_em=raw["coleta"])
    return {"aquisicao":{k:v for k,v in raw.items() if k!="bytes"},"dados":dados}
