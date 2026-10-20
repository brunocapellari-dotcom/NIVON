"""Validação de precipitação CHIRPS v3 por pêntada.

CHIRPS v3 daily RNL e SAT são redistribuições dos totais pentadais,
não observações diárias independentes. Não combinar séries RNL/SAT,
preliminar/final ou versões em um único registro canônico sem origem.
"""
from __future__ import annotations
import calendar
from datetime import date,timedelta
from math import isfinite

class ErroCHIRPS(ValueError):
    pass

def dias_pentada(ano:int,mes:int,pentada:int):
    if type(ano) is not int or type(mes) is not int or type(pentada) is not int:
        raise ErroCHIRPS("competência de pêntada inválida")
    if not 1981<=ano<=2100 or not 1<=mes<=12 or not 1<=pentada<=6:
        raise ErroCHIRPS("ano/mês/pêntada fora dos limites")
    inicio=(pentada-1)*5+1
    fim=min(pentada*5,calendar.monthrange(ano,mes)[1]) if pentada<6 else calendar.monthrange(ano,mes)[1]
    return [date(ano,mes,d).isoformat() for d in range(inicio,fim+1)]

def reconciliar_chirps_pentada(*,ano:int,mes:int,pentada:int,
                              chuva_total_pentada_mm,chuva_diaria:list[dict],
                              diario_tipo:str,versao:str,estado:str,
                              fonte_temporal:str,tolerancia_mm=0.1):
    """Concilia o volume pentadal da MESMA célula espacial já validada.

    Series a montante precisam ser pareadas por célula/CRS/máscara;
    esta função não converte grade nem georreferencia arquivo.
    """
    if diario_tipo not in {"rnl","sat"} or versao!="3.0" or estado not in {"PRELIMINAR","FINAL"}:
        raise ErroCHIRPS("versão/produto diário/estado precisam ser explícitos")
    if not isinstance(fonte_temporal,str) or len(fonte_temporal.strip())<8:
        raise ErroCHIRPS("evidência de versão do arquivo/grade obrigatória")
    if type(chuva_total_pentada_mm) not in (int,float) or not isfinite(chuva_total_pentada_mm) or chuva_total_pentada_mm<0:
        raise ErroCHIRPS("chuva pentadal inválida")
    if type(tolerancia_mm) not in (int,float) or not isfinite(tolerancia_mm) or not 0<=tolerancia_mm<=1:
        raise ErroCHIRPS("tolerância fora do limite")
    dias=dias_pentada(ano,mes,pentada)
    if not isinstance(chuva_diaria,list) or len(chuva_diaria)!=len(dias):
        raise ErroCHIRPS("pêntada sem todos os dias")
    visto=set();total=0.
    for obj in chuva_diaria:
        if not isinstance(obj,dict):raise ErroCHIRPS("item diário inválido")
        d=obj.get("data")
        if d not in dias or d in visto:raise ErroCHIRPS("data duplicada/fora da pêntada")
        visto.add(d)
        for key,value in (("produto",diario_tipo),("versao",versao),("estado",estado)):
            if obj.get(key)!=value:
                raise ErroCHIRPS("mistura de produtos, versões ou status")
        x=obj.get("chuva_mm")
        if type(x) not in (int,float) or not isfinite(x) or x<0:
            raise ErroCHIRPS("chuva negativa, nula ou faltante")
        total+=x
    if set(dias)!=visto:raise ErroCHIRPS("data faltante")
    erro=total-chuva_total_pentada_mm
    if abs(erro)>tolerancia_mm:
        raise ErroCHIRPS("volume diário não concilia com a pêntada")
    return {"versao":"CHIRPS_3.0","estado":estado,"tipo_diario":diario_tipo,
            "ano":ano,"mes":mes,"pentada":pentada,
            "dias":len(dias),"soma_chuva_diaria_mm":total,
            "chuva_pentada_mm":float(chuva_total_pentada_mm),
            "erro_conservacao_mm":erro,
            "fonte":fonte_temporal,"classificacao":"CHIRPS_GRADE_ESTIMATIVA_COM_CONSERVACAO",
            "limites":"Diário SAT usa IMERG Late e RNL usa ERA5 na partição; "
                      "não equivale a janela uniforme de pluviômetro nem dado atual."}
