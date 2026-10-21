"""Open-Meteo GloFAS (vazão simulada) e Ensemble (chuva probabilística).

Consultas HTTPS pontuais; não é vazão observada ANA nem chuva de estação.
Sem previsão de navegabilidade automaticamente a partir da vazão de grade.
"""
from __future__ import annotations
import hashlib
import json
import math
import re
from datetime import date, datetime, timezone
from urllib.parse import urlencode
from .apis_gratuitas_execucao import _obter_json


class ErroAgroClimaAberto(ValueError):
    pass


FLOOD = "https://flood-api.open-meteo.com/v1/flood"
ENSEMBLE = "https://ensemble-api.open-meteo.com/v1/ensemble"


def _coord(lat, lon):
    if any(type(n) not in (float, int) or not math.isfinite(n) for n in (lat, lon)):
        raise ErroAgroClimaAberto("coordenadas inválidas")
    if not -90 <= lat <= 90 or not -180 <= lon <= 180:
        raise ErroAgroClimaAberto("coordenadas fora do WGS84")


def _json(payload, limite):
    if not isinstance(payload, bytes) or not 1 <= len(payload) <= limite:
        raise ErroAgroClimaAberto("resposta vazia ou grande demais")
    def unique(pairs):
        o = {}
        for k,v in pairs:
            if k in o:
                raise ErroAgroClimaAberto("chaves JSON duplicadas")
            o[k] = v
        return o
    try:
        o = json.loads(payload.decode("utf-8-sig"), object_pairs_hook=unique)
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise ErroAgroClimaAberto("resposta JSON inválida") from exc
    if not isinstance(o, dict) or o.get("error") is True:
        raise ErroAgroClimaAberto("resposta falha ou não é objeto")
    return o


def _data_coleta(s):
    if not isinstance(s,str):
        raise ErroAgroClimaAberto("coleta inválida")
    try:
        d=datetime.fromisoformat(s.replace("Z","+00:00"))
    except ValueError as exc:
        raise ErroAgroClimaAberto("coleta inválida") from exc
    if d.tzinfo is None or d.utcoffset() is None:
        raise ErroAgroClimaAberto("coleta sem fuso")
    return d.astimezone(timezone.utc).isoformat()


def _serie_num(arr,n,*,label):
    if not isinstance(arr,list) or len(arr)!=n:
        raise ErroAgroClimaAberto(label+": vetor fora de tamanho")
    for x in arr:
        if x is not None and (type(x) not in (int,float) or not math.isfinite(x) or x<0 or x>1e9):
            raise ErroAgroClimaAberto(label+": número inválido")


def planejar_vazao(*,latitude,longitude,dias=7):
    _coord(latitude,longitude)
    if type(dias) is not int or not 1<=dias<=14:
        raise ErroAgroClimaAberto("janela máxima de 14 dias")
    return FLOOD+"?"+urlencode({"latitude":latitude,"longitude":longitude,
        "daily":"river_discharge","timezone":"GMT","forecast_days":dias,"past_days":0})


def normalizar_vazao(payload,*,latitude,longitude,dias,coletado_em):
    url=planejar_vazao(latitude=latitude,longitude=longitude,dias=dias)
    o=_json(payload,750_000)
    if o.get("utc_offset_seconds") != 0:
        raise ErroAgroClimaAberto("API deve retornar tempo em GMT")
    d=o.get("daily"); units=o.get("daily_units")
    if not isinstance(d,dict) or not isinstance(units,dict):
        raise ErroAgroClimaAberto("daily/daily_units ausentes")
    if units.get("river_discharge") not in ("m³/s","m3/s"):
        raise ErroAgroClimaAberto("vazão deve estar em m³/s")
    times=d.get("time"); vals=d.get("river_discharge")
    if not isinstance(times,list) or not 1<=len(times)<=dias:
        raise ErroAgroClimaAberto("datas incompatíveis com janela")
    _serie_num(vals,len(times),label="river_discharge")
    obs=[]
    for data,v in zip(times,vals):
        try:
            parsed=date.fromisoformat(data)
        except (TypeError,ValueError) as exc:
            raise ErroAgroClimaAberto("data vazão inválida") from exc
        if obs and data<=obs[-1]["data_referencia"]:
            raise ErroAgroClimaAberto("datas não ordenadas")
        obs.append({"data_referencia":parsed.isoformat(),"competencia":parsed.strftime("%Y-%m"),
            "vazao_simulada_m3_s":v,"unidade":"m³/s",
            "natureza":"PROJETADO_MODELO_GLOFAS_NAO_MEDICAO_ANA",
            "publicacao":None,"coleta":_data_coleta(coletado_em)})
    return {"dataset_id":"OPEN_METEO_GLOFAS_VAZAO","fonte_id":"OPEN_METEO",
        "consulta_url":url,"observacoes":obs,"quantidade":len(obs),
        "resolucao_aproximada_km":5,"modelo_fonte":"GLOFAS_V4",
        "vinculo_estacao_ANA_validado":False,"navegabilidade_inferivel":False,
        "sha256_original":hashlib.sha256(payload).hexdigest(),
        "apto_publicacao_automatica":False,"estado":"PONTUAL_VAZAO_MODELADA_NAO_OPERACIONAL"}


def consultar_vazao(*,latitude,longitude,dias=7,executar=False,abridor=None,instante=None):
    url=planejar_vazao(latitude=latitude,longitude=longitude,dias=dias)
    raw=_obter_json(url,recurso="open_flood",executar=executar,abridor=abridor,instante=instante)
    res=normalizar_vazao(raw["bytes"],latitude=latitude,longitude=longitude,dias=dias,coletado_em=raw["coleta"])
    return {"aquisicao":{k:v for k,v in raw.items() if k!="bytes"},"dados":res}


def planejar_ensemble(*,latitude,longitude,dias=3,modelo="gfs_seamless"):
    _coord(latitude,longitude)
    if type(dias) is not int or not 1<=dias<=7:
        raise ErroAgroClimaAberto("janela 1 a 7 dias")
    # Permite revisar modelo somente após resposta real validada.
    if modelo not in ("gfs_seamless","gfs025"):
        raise ErroAgroClimaAberto("modelo ensemble não homologado")
    return ENSEMBLE+"?"+urlencode({"latitude":latitude,"longitude":longitude,
        "hourly":"precipitation","models":modelo,"timezone":"GMT",
        "forecast_days":dias,"past_days":0})


def normalizar_ensemble(payload,*,latitude,longitude,dias,modelo,coletado_em):
    url=planejar_ensemble(latitude=latitude,longitude=longitude,dias=dias,modelo=modelo)
    o=_json(payload,1_500_000)
    if o.get("utc_offset_seconds") != 0:
        raise ErroAgroClimaAberto("timezone divergente")
    h=o.get("hourly"); units=o.get("hourly_units")
    if not isinstance(h,dict) or not isinstance(units,dict):
        raise ErroAgroClimaAberto("hourly/units ausentes")
    t=h.get("time")
    if not isinstance(t,list) or not 1<=len(t)<=dias*24:
        raise ErroAgroClimaAberto("tempos horários ausentes/excessivos")
    for value in t:
        if not isinstance(value,str) or not re.fullmatch(r"\d{4}-\d\d-\d\dT\d\d:\d\d",value):
            raise ErroAgroClimaAberto("hora de modelo inválida")
    if len(set(t))!=len(t) or sorted(t)!=t:
        raise ErroAgroClimaAberto("horas repetidas/fora de ordem")
    # Observações de membros são séries independentes. NUNCA média não ponderada
    # entre modelos diferentes, nunca forecast observada.
    keys=[k for k in h if k.startswith("precipitation_member")]
    if not 1<=len(keys)<=100:
        raise ErroAgroClimaAberto("nenhum membro ensemble na resposta")
    if len(h)!=(len(keys)+1):
        raise ErroAgroClimaAberto("campos horários inesperados")
    for k in keys:
        if units.get(k)!="mm":
            raise ErroAgroClimaAberto("unidade precipitação diferente de mm")
        _serie_num(h[k],len(t),label=k)
    return {"dataset_id":"OPEN_METEO_ENSEMBLE_PRECIP_MEMBROS","fonte_id":"OPEN_METEO",
        "consulta_url":url,"modelo":modelo,"horas":t,
        "membros":{k:h[k] for k in sorted(keys)},"numero_membros":len(keys),
        "numero_horas":len(t),"unidade":"mm/hora_modelada",
        "natureza":"PROJETADO_ENSEMBLE_NAO_CHUVA_OBSERVADA",
        "coleta":_data_coleta(coletado_em),"publicacao":None,
        "sha256_original":hashlib.sha256(payload).hexdigest(),
        "apto_probabilidade_calibrada":False,"apto_publicacao_automatica":False,
        "estado":"PONTUAL_ENSEMBLE_NAO_CALIBRADO"}


def consultar_ensemble(*,latitude,longitude,dias=3,modelo="gfs_seamless",executar=False,abridor=None,instante=None):
    url=planejar_ensemble(latitude=latitude,longitude=longitude,dias=dias,modelo=modelo)
    raw=_obter_json(url,recurso="open_ensemble",executar=executar,abridor=abridor,instante=instante)
    res=normalizar_ensemble(raw["bytes"],latitude=latitude,longitude=longitude,dias=dias,modelo=modelo,coletado_em=raw["coleta"])
    return {"aquisicao":{k:v for k,v in raw.items() if k!="bytes"},"dados":res}
