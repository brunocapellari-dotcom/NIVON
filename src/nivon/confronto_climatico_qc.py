"""Confronto offline estação INMET vs grade NASA POWER, com gates de proveniência.

Comparação NÃO constitui previsão nem treinamento; INMET e NASA têm suporte
espacial/temporal diferente. Exige QC externo e prova documental do intervalo.
"""
from __future__ import annotations
from datetime import date,datetime,timezone
from hashlib import sha256
from math import asin,cos,radians,sin,sqrt,isfinite
import re

from .inmet_horario_qc import ErroINMETHorario
from .validacao_previsoes_ambientais import confrontar_grade_com_estacao

_SHA=re.compile(r"[a-f0-9]{64}\Z")


def _coords(value,label):
    if (not isinstance(value,(tuple,list)) or len(value)!=2
        or any(type(z) not in (int,float) or not isfinite(z) for z in value)):
        raise ErroINMETHorario(label+": coordenadas ausentes ou inválidas")
    lat,lon=value
    if not -90<=lat<=90 or not -180<=lon<=180:
        raise ErroINMETHorario(label+": coordenadas fora dos limites")
    return lat,lon


def _distancia_km(a,b):
    x,y=_coords(a,"estação");u,v=_coords(b,"grade")
    f=radians(u-x);l=radians(v-y)
    h=sin(f/2)**2+cos(radians(x))*cos(radians(u))*sin(l/2)**2
    return 2*6371.0088*asin(min(1,sqrt(h)))


def confronto_diario_inmet_power(
    *, diario_inmet:dict, grade_nasa:list[dict],
    coordenadas_estacao:tuple, qc_externo:dict,
    fonte_coordenadas:str, corte_coleta:str,
) -> dict:
    """NASA precisa vir de grade_asof(...) com edições publicadas.

    QC externo é declaração a ser auditada contra laboratório/estação e RAW;
    não emitimos indicador homologado. Estações com dados insuficientes não
    recebem MAE, nem chuva faltante é substituída por zero.
    """
    if not isinstance(diario_inmet,dict) or diario_inmet.get("status")!="DIARIO_PRELIMINAR_NAO_HOMOLOGADO":
        raise ErroINMETHorario("entrada diária INMET inválida")
    if not isinstance(fonte_coordenadas,str) or len(fonte_coordenadas.strip())<12:
        raise ErroINMETHorario("proveniência geodésica da estação obrigatória")
    if not isinstance(qc_externo,dict) or qc_externo.get("aprovado") is not True:
        raise ErroINMETHorario("QC instrumental independente pendente")
    if (qc_externo.get("estacao")!=diario_inmet.get("estacao") or
        qc_externo.get("raw_sha256")!=diario_inmet.get("raw_sha256") or
        not isinstance(qc_externo.get("relatorio_sha256"),str) or
        not _SHA.fullmatch(qc_externo["relatorio_sha256"])):
        raise ErroINMETHorario("prova QC deve vincular estação e RAW exatos")
    if not isinstance(grade_nasa,list) or len(grade_nasa)>50000:
        raise ErroINMETHorario("série de grade desconhecida/excessiva")
    try:corte=datetime.fromisoformat(corte_coleta.replace("Z","+00:00"))
    except (ValueError,AttributeError) as exc:
        raise ErroINMETHorario("corte com fuso obrigatório") from exc
    if corte.tzinfo is None or corte.utcoffset() is None:
        raise ErroINMETHorario("corte sem fuso")
    corte=corte.astimezone(timezone.utc)
    if not grade_nasa:
        return {"status":"SEM_GRADE_HISTORICA_NO_CORTE",
                "pares":0,"homologado":False,"skill_preditiva_comprovada":False}
    coord_ref=None;versoes=set();byday={}
    for r in grade_nasa:
        if not isinstance(r,dict) or r.get("unidade")!="MM_DIA":
            raise ErroINMETHorario("somente NASA chuva diária em mm/dia")
        point=_coords((r.get("latitude_grade"),r.get("longitude_grade")),"grade")
        if coord_ref is not None and coord_ref!=point:
            raise ErroINMETHorario("células NASA diferentes no mesmo confronto")
        coord_ref=point
        h=r.get("conteudo_sha256")
        if not isinstance(h,str) or not _SHA.fullmatch(h):
            raise ErroINMETHorario("hash de vintage NASA inválido")
        versions=(h,r.get("publicado_utc"))
        versoes.add(versions)
        try:
            publicado=datetime.fromisoformat(r["publicado_utc"].replace("Z","+00:00"))
            coletado=datetime.fromisoformat(r["primeira_coleta_utc"].replace("Z","+00:00"))
        except (ValueError,TypeError,KeyError,AttributeError) as exc:
            raise ErroINMETHorario("proveniência temporal NASA incompleta") from exc
        if (publicado.tzinfo is None or coletado.tzinfo is None
            or publicado>corte or coletado>corte or publicado>coletado):
            raise ErroINMETHorario("vintage NASA posterior ao corte ou inválido")
        dia=r.get("data_utc")
        try:date.fromisoformat(dia)
        except (TypeError,ValueError) as exc:raise ErroINMETHorario("dia grade inválido") from exc
        value=r.get("valor")
        if value is not None and (type(value) not in (int,float) or not isfinite(value) or value<0):
            raise ErroINMETHorario("chuva grade fisicamente inválida")
        if dia in byday:
            raise ErroINMETHorario("revisões duplicadas para o mesmo dia")
        byday[dia]=value
    distance=_distancia_km(coordenadas_estacao,coord_ref)
    if distance>150:
        raise ErroINMETHorario("estação distante demais da célula, misturar dados proibido")
    candidates=[]
    for row in diario_inmet["dias"]:
        if row.get("comparacao_grade_permitida") is not True:
            continue
        d=row["data_utc"]
        if d not in byday or byday[d] is None:
            continue
        rain=row.get("chuva_rotulo_utc_mm")
        if type(rain) not in (int,float) or not isfinite(rain) or rain<0:
            raise ErroINMETHorario("dado de estação inválido")
        candidates.append({"data":d,"qualidade_estacao":"APROVADO",
                           "valor_estacao":rain,"valor_grade":byday[d]})
    if len(candidates)<30:
        return {"status":"COBERTURA_INSUFICIENTE_PARA_SCORE",
                "pares":len(candidates),"dias_estacao":len(diario_inmet["dias"]),
                "dias_grade":len(grade_nasa),"distancia_km":distance,
                "qc_declarado_externamente":True,"homologado":False,
                "skill_preditiva_comprovada":False}
    result=confrontar_grade_com_estacao(
        pares_diarios=candidates,estacao_id=diario_inmet["estacao"],
        produto_grade="NASA_POWER_AG:PRECTOTCORR",
        distancia_centro_grade_km=distance,
        fonte_medida="INMET_ESTACOES:UTC_DIARIO_SEM_QC_AUTOMATICO",
        metrica="CHUVA_DIA_MM",unidade="MM",
    )
    return {**result,"status":"CONFRONTO_DESCRITIVO_COM_QC_EXTERNO_DECLARADO",
            "qc_evidencia_sha256":qc_externo["relatorio_sha256"],
            "inmet_raw_sha256":diario_inmet["raw_sha256"],
            "vintages_grade":len(versoes),
            "homologado":False,"skill_preditiva_comprovada":False,
            "limitacao_adicional":"Revisões e sensores devem ter prova auditada; comparação retrospectiva não mede skill de previsão"}
