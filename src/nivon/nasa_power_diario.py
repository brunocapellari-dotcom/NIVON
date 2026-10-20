"""Contrato de acesso/normalização NASA POWER Daily, sem coleta automática.

Daily API informa LST por padrão; Nivon exige UTC explícito e recortes
curtos. Dados de grade/reanálise não são medição direta INMET nem chuva
observada em fazenda. Radiação solar de ondas curtas NÃO é Rn FAO56.
"""
from __future__ import annotations
import json
import re
from datetime import date, timedelta
from math import isfinite
from urllib.parse import urlencode, urlsplit

BASE="https://power.larc.nasa.gov/api/temporal/daily/point"
PARAMETROS={
 "T2M_MAX":("CELSIUS",-70,65),
 "T2M_MIN":("CELSIUS",-70,65),
 "PRECTOTCORR":("MM_DIA",0,800),
 "RH2M":("PERCENTUAL",0,100),
 "WS2M":("M_S",0,60),
 "ALLSKY_SFC_SW_DWN":("KWH_M2_DIA",0,20),
}
class ErroPower(ValueError):
    pass

def planejar_power(*,latitude,longitude,inicio,fim,parametros=("PRECTOTCORR","T2M_MAX","T2M_MIN")):
    if any(type(x) not in (float,int) or not isfinite(x) for x in (latitude,longitude)) or not (-90<=latitude<=90 and -180<=longitude<=180):
        raise ErroPower("coordenadas lat/lon inválidas")
    if (not isinstance(parametros,(list,tuple)) or not 1<=len(parametros)<=20
        or len(set(parametros))!=len(parametros) or not set(parametros)<=set(PARAMETROS)):
        raise ErroPower("parâmetros não homologados")
    try:
        a=date.fromisoformat(inicio);b=date.fromisoformat(fim)
    except (ValueError,TypeError) as exc:
        raise ErroPower("datas YYYY-MM-DD inválidas") from exc
    if a>b or (b-a).days>=366:
        raise ErroPower("dividir histórico em janelas <=366 dias")
    args={"parameters":",".join(parametros),"community":"AG",
          "longitude":f"{longitude:.5f}","latitude":f"{latitude:.5f}",
          "start":a.strftime("%Y%m%d"),"end":b.strftime("%Y%m%d"),
          "format":"JSON","time-standard":"UTC"}
    return {"dataset_id":"NASA_POWER_AG","url":BASE+"?"+urlencode(args),
            "inicio":inicio,"fim":fim,"parametros":list(parametros),
            "time_standard":"UTC","executar":False,
            "intervalo_dias":(b-a).days+1,
            "direitos_e_parser_reais_homologados":False}

def _pares(pairs):
    out={}
    for key,val in pairs:
        if key in out: raise ErroPower("JSON com chave repetida")
        out[key]=val
    return out

def normalizar_power_diario(*,bytes_json,plano,sha256,coletado_em):
    """Converte série da grade em linhas diárias, sem preencher faltantes."""
    if not isinstance(bytes_json,bytes) or not 1<=len(bytes_json)<=2_000_000:
        raise ErroPower("payload JSON inválido ou grande demais")
    if (not isinstance(plano,dict) or plano.get("dataset_id")!="NASA_POWER_AG" or
        plano.get("time_standard")!="UTC" or plano.get("executar") is not False):
        raise ErroPower("plano oficial inválido")
    if not isinstance(sha256,str) or not re.fullmatch(r"[0-9a-f]{64}",sha256):
        raise ErroPower("SHA ausente")
    from datetime import datetime,timezone
    try:coleta=datetime.fromisoformat(coletado_em.replace("Z","+00:00"))
    except (ValueError,AttributeError) as exc:
        raise ErroPower("coleta sem timestamp") from exc
    if coleta.tzinfo is None or coleta.utcoffset() is None: raise ErroPower("timezone coleta obrigatório")
    p=urlsplit(plano["url"])
    if p.scheme!="https" or p.hostname!="power.larc.nasa.gov" or p.path!="/api/temporal/daily/point":
        raise ErroPower("origem NASA POWER não permitida")
    try:payload=json.loads(bytes_json.decode("utf-8-sig"),object_pairs_hook=_pares)
    except (UnicodeError,json.JSONDecodeError) as exc:
        raise ErroPower("JSON NASA inválido") from exc
    series=payload.get("properties",{}).get("parameter",{})
    if not isinstance(series,dict) or set(series)!=set(plano["parametros"]):
        raise ErroPower("parâmetros NASA ausentes ou não solicitados")
    dates=set()
    for k,v in series.items():
        if not isinstance(v,dict) or not v:
            raise ErroPower("série de parâmetro vazia")
        dates.update(v)
    expected=[(date.fromisoformat(plano["inicio"])+timedelta(days=i)).strftime("%Y%m%d") for i in range(plano["intervalo_dias"])]
    if set(expected)!=dates:
        raise ErroPower("janela NASA incompleta, excessiva ou com lacuna")
    rows=[]
    for day in expected:
        values={};missing=[]
        for key,(_,lo,hi) in PARAMETROS.items():
            if key not in series:continue
            if day not in series[key]:raise ErroPower("parâmetro faltando no dia")
            value=series[key][day]
            if type(value) not in (int,float) or not isfinite(value):
                raise ErroPower("valor NASA inválido")
            if value==-999:
                values[key]=None;missing.append(key)
            elif lo<=value<=hi:
                values[key]=float(value)
            else:raise ErroPower("unidade/limite meteorológico NASA inconsistente")
        if values.get("T2M_MIN") is not None and values.get("T2M_MAX") is not None and values["T2M_MIN"]>values["T2M_MAX"]:
            raise ErroPower("temperaturas diárias incoerentes")
        rows.append({"data_utc":date.fromisoformat(day[:4]+"-"+day[4:6]+"-"+day[6:]).isoformat(),
                     "valores":values,"ausentes":missing,"coleta":coleta.astimezone(timezone.utc).isoformat(),
                     "fonte_id":"NASA_POWER","dataset_id":"NASA_POWER_AG","sha256":sha256,
                     "natureza":"ESTIMADO_REANALISE_GRADE",
                     "publicacao":None,"validado_com_estacao":False})
    return {"registros":rows,"numero_dias":len(rows),"parametros":plano["parametros"],
            "periodo":(plano["inicio"],plano["fim"]),"escala_temporal":"DIARIA_UTC",
            "conversao_rad_liquida_fao56_realizada":False,
            "classificacao":"RESPOSTA_POWER_NAO_E_MEDICAO_LOCAL",
            "apto_previsao_homologada":False}
