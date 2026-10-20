"""NASA POWER diário: adaptador do coletor AgroLogMT, SEM agendamento.

Somente endpoint NASA permitido, parâmetros em allowlist, resposta limitada,
sem seguir redirects e fail-closed até direito de coleta confirmado por operação.
Valores em grade são ESTIMADOS (não medições in situ). Data de publicação ausente
não pode ser preenchida com data de coleta; vintages históricas precisam prova.
"""
from __future__ import annotations
from datetime import date,datetime,timezone
from math import isfinite
from urllib.parse import urlencode,urlsplit
from urllib.request import Request,build_opener,HTTPRedirectHandler
import json,re

from .qualidade_cientifica import ErroCientifico

BASE="https://power.larc.nasa.gov/api/temporal/daily/point"
PERMITIDOS=("PRECTOTCORR","T2M","T2M_MAX","T2M_MIN","RH2M")
NOMES_UNIDADES={"PRECTOTCORR":"mm/dia","T2M":"C","T2M_MAX":"C","T2M_MIN":"C","RH2M":"percentual"}
MAX_BYTES=4_000_000


def url_diaria(*,latitude,longitude,inicio:date,fim:date,parametros:tuple=PERMITIDOS):
    for valor,limite,nome in ((latitude,90,"latitude"),(longitude,180,"longitude")):
        if type(valor) not in (float,int) or not isfinite(valor) or not -limite<=valor<=limite:
            raise ErroCientifico(f"{nome}: coordenada inválida")
    if (type(inicio) is not date or type(fim) is not date or fim<inicio
        or (fim-inicio).days>365 or inicio.year<1981):
        raise ErroCientifico("janela anual histórica NASA POWER inválida")
    if (not isinstance(parametros,tuple) or not parametros
        or len(set(parametros))!=len(parametros)
        or not set(parametros)<=set(PERMITIDOS)):
        raise ErroCientifico("variáveis NASA POWER fora da allowlist")
    return BASE+"?"+urlencode({
        "parameters":",".join(parametros),"community":"AG",
        "longitude":f"{longitude:.6f}","latitude":f"{latitude:.6f}",
        "start":inicio.strftime("%Y%m%d"),"end":fim.strftime("%Y%m%d"),
        "format":"JSON","time-standard":"UTC"
    })


def normalizar_resposta(payload:dict,*,parametros:tuple,inicio:date,fim:date,
                        coletado_em:str,fonte_url:str,
                        latitude_solicitada:float|None=None,
                        longitude_solicitada:float|None=None) -> list[dict]:
    if not isinstance(payload,dict) or payload.get("type") not in (None,"Feature"):
        raise ErroCientifico("payload POWER inválido")
    geo=payload.get("geometry",{}).get("coordinates")
    if (not isinstance(geo,(tuple,list)) or len(geo)<2
        or any(type(v) not in (int,float) or not isfinite(v) for v in geo[:2])):
        raise ErroCientifico("coordenadas de origem ausentes")
    lon,lat=geo[:2]
    if not -180<=lon<=180 or not -90<=lat<=90:
        raise ErroCientifico("coordenadas do payload inconsistentes")
    # Grade NASA pode representar ponto próximo, mas não outra região.
    if latitude_solicitada is not None and abs(lat-latitude_solicitada)>0.75:
        raise ErroCientifico("grade de latitude diferente da região solicitada")
    if longitude_solicitada is not None and abs(lon-longitude_solicitada)>0.75:
        raise ErroCientifico("grade de longitude diferente da região solicitada")
    p=payload.get("properties",{}).get("parameter")
    if not isinstance(p,dict) or set(p)!=set(parametros):
        raise ErroCientifico("parâmetros recebidos diferem dos solicitados")
    d=datetime.fromisoformat(coletado_em.replace("Z","+00:00"))
    if d.tzinfo is None:raise ErroCientifico("coleta com fuso obrigatório")
    source=urlsplit(fonte_url)
    if (source.scheme!="https" or source.hostname!="power.larc.nasa.gov"
        or source.username or source.password or source.port not in (None,443)):
        raise ErroCientifico("URL da evidência NASA insegura")
    valores=[]
    duplicados=set()
    for parametro in parametros:
        serie=p[parametro]
        if not isinstance(serie,dict):raise ErroCientifico("série por parâmetro inválida")
        for dia,valor in serie.items():
            if not isinstance(dia,str) or not re.fullmatch(r"[0-9]{8}",dia):
                raise ErroCientifico("dia fora do formato NASA POWER")
            try:dt=datetime.strptime(dia,"%Y%m%d").date()
            except ValueError as ex:raise ErroCientifico("data calendário inválida") from ex
            if not inicio<=dt<=fim or (parametro,dt) in duplicados:
                raise ErroCientifico("data fora da janela ou duplicada")
            duplicados.add((parametro,dt))
            try:v=float(valor) if valor is not None else None
            except (TypeError,ValueError) as ex:raise ErroCientifico("valor não numérico") from ex
            if v is not None and not isfinite(v):
                raise ErroCientifico("valor NASA NaN/inf")
            if v is not None and v<=-999:
                v=None
            if v is not None:
                if parametro in ("PRECTOTCORR","RH2M") and v<0:
                    raise ErroCientifico("chuva/umidade física negativa")
                if parametro=="RH2M" and v>100:
                    raise ErroCientifico("umidade relativa superior a 100%")
            valores.append({"source_id":"NASA_POWER","dataset_id":"NASA_POWER_AGRO_DAILY",
                "competencia":dt.isoformat(),"referencia":dt.isoformat(),
                "publicacao":None,"coleta":coletado_em,
                "latitude":lat,"longitude":lon,"variavel":parametro,
                "valor":v,"unidade":NOMES_UNIDADES[parametro],
                "natureza":"ESTIMADO","subtipo":"GRADE_NASA_POWER",
                "fonte_url":fonte_url})
    # Identidade térmica: média diária entre mínima e máxima da MESMA fonte.
    por_dia={}
    for registro in valores:
        por_dia.setdefault(registro["competencia"],{})[registro["variavel"]]=registro["valor"]
    for dia,serie in por_dia.items():
        mn=serie.get("T2M_MIN");me=serie.get("T2M");mx=serie.get("T2M_MAX")
        if mn is not None and mx is not None and mn>mx:
            raise ErroCientifico("TMIN>TMAX na série NASA POWER: "+dia)
        if me is not None and mn is not None and me<mn-0.01:
            raise ErroCientifico("temperatura média inferior à mínima física no dia: "+dia)
        if me is not None and mx is not None and me>mx+0.01:
            raise ErroCientifico("temperatura média superior à máxima física no dia: "+dia)
    return sorted(valores,key=lambda x:(x["competencia"],x["variavel"]))


class _BloquearRedirecionamento(HTTPRedirectHandler):
    def redirect_request(self,*args,**kwargs):
        raise ErroCientifico("redirects bloqueados em fonte oficial")


def coletar_diario(*,latitude,longitude,inicio:date,fim:date,
                   direitos_confirmados:bool=False,parametros:tuple=PERMITIDOS) -> list[dict]:
    if direitos_confirmados is not True:
        raise PermissionError("NASA POWER sem aprovação por operação: coleta bloqueada")
    url=url_diaria(latitude=latitude,longitude=longitude,inicio=inicio,
                   fim=fim,parametros=parametros)
    opener=build_opener(_BloquearRedirecionamento())
    req=Request(url,headers={"User-Agent":"NIVON/0.1 NASA-POWER manual authorized source"})
    with opener.open(req,timeout=25) as response:
        url_resposta=response.geturl()
        u=urlsplit(url_resposta)
        if u.scheme!="https" or u.hostname!="power.larc.nasa.gov" or u.username or u.password:
            raise ErroCientifico("host NASA da resposta divergente")
        if "json" not in response.headers.get("Content-Type","").lower():
            raise ErroCientifico("NASA POWER: MIME não JSON")
        raw=response.read(MAX_BYTES+1)
        if len(raw)>MAX_BYTES:
            raise ErroCientifico("resposta NASA POWER excessiva")
        payload=json.loads(raw.decode("utf-8"))
    return normalizar_resposta(payload,parametros=parametros,inicio=inicio,fim=fim,
        coletado_em=datetime.now(timezone.utc).isoformat(),fonte_url=url_resposta,
        latitude_solicitada=latitude,longitude_solicitada=longitude)
