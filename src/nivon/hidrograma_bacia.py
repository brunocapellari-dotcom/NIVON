"""Chuva subdiária -> perda SCS-CN por EVENTO -> hidrograma conservativo.

CN must apply to CUMULATIVE event precipitation, NOT independently to each
hour. Excess increments are routed through a nonnegative discrete unit
hydrograph, normalized to unit volume. The full recession tail is preserved.
Output is direct runoff only; not observed stage or navigation clearance.
"""
from __future__ import annotations
from datetime import datetime,timedelta,timezone
from math import isfinite,fsum
from .hidrologia_chuva_vazao import escoamento_scs_cn, ErroChuvaVazao

class ErroHidrograma(ValueError):
    pass

def _value(v, label,minimum=None,maximum=None):
    if type(v) not in (int,float) or not isfinite(v):
        raise ErroHidrograma(label+": número real finito obrigatório")
    val=float(v)
    if minimum is not None and val<minimum or maximum is not None and val>maximum:
        raise ErroHidrograma(label+": fora do domínio")
    return val

def _when(s):
    if not isinstance(s,str) or "T" not in s:
        raise ErroHidrograma("timestamp ISO com fuso obrigatório")
    try:t=datetime.fromisoformat(s.replace("Z","+00:00"))
    except ValueError as e:raise ErroHidrograma("timestamp inválido") from e
    if t.tzinfo is None or t.utcoffset() is None:
        raise ErroHidrograma("timestamp sem fuso")
    return t.astimezone(timezone.utc)

def hidrograma_evento_cn(*,chuva_intervalos,passo_horas,numero_curva,
                        area_bacia_km2,fracao_abstracao_inicial,
                        resposta_unitaria_pesos,
                        fonte_chuva,fonte_cn,fonte_resposta_unitaria,
                        bacia_id):
    """A unit hydrograph can be supplied from calibrated HEC-HMS / observations.

    The input of each time step is precipitation depth mm OVER THE BASIN
    representative area; per-point precipitation or sparse grids require
    areal weighting upstream. A UH kernel weights discharge volume by step.
    """
    for src in (fonte_chuva,fonte_cn,fonte_resposta_unitaria,bacia_id):
        if not isinstance(src,str) or len(src.strip())<5 or len(src)>250:
            raise ErroHidrograma("bacia e fontes de parâmetros obrigatórias")
    step=_value(passo_horas,"passo_horas",1/60,72)
    area=_value(area_bacia_km2,"area",.001,1e7)
    # Validate the CN/initial abstraction contract even when all rainfall is zero.
    try:
        escoamento_scs_cn(chuva_evento_mm=0,numero_curva=numero_curva,
            area_bacia_km2=area,fracao_abstracao_inicial=fracao_abstracao_inicial,
            fonte_cn=fonte_cn,fonte_chuva=fonte_chuva)
    except ErroChuvaVazao as e:
        raise ErroHidrograma("parâmetros NRCS inválidos") from e
    if not isinstance(chuva_intervalos,(list,tuple)) or not 2<=len(chuva_intervalos)<=5000:
        raise ErroHidrograma("evento requer 2 a 5000 passos")
    if not isinstance(resposta_unitaria_pesos,(list,tuple)) or not 1<=len(resposta_unitaria_pesos)<=500:
        raise ErroHidrograma("hidrograma unitário requer 1 a 500 pesos")
    weights=[_value(v,"peso resposta",0,1) for v in resposta_unitaria_pesos]
    total_weights=fsum(weights)
    if total_weights<=0 or abs(total_weights-1)>1e-8:
        raise ErroHidrograma("resposta unitária precisa conservar 100% do escoamento")
    if not any(w>0 for w in weights):
        raise ErroHidrograma("hidrograma unitário degenerado")
    # Reject tails which leave deliberate artificial drainage unaccounted.
    rain=[];previous_time=None;rain_sum=0.
    for item in chuva_intervalos:
        if not isinstance(item,dict) or set(item)!={"data_hora","chuva_area_mm"}:
            raise ErroHidrograma("item de chuva fora do contrato")
        t=_when(item["data_hora"])
        if previous_time is not None:
            dt=(t-previous_time).total_seconds()/3600
            if abs(dt-step)>1e-8:
                raise ErroHidrograma("lacuna, duplicata ou passo temporal irregular")
        v=_value(item["chuva_area_mm"],"chuva areal",0,2000)
        rain.append((t,v))
        rain_sum+=v
        if rain_sum>5000:
            raise ErroHidrograma("chuva de evento acima do limite")
        previous_time=t
    cumulative=0.;previous_excess=0.;increments=[]
    for _,value in rain:
        cumulative+=value
        q=escoamento_scs_cn(chuva_evento_mm=cumulative,numero_curva=numero_curva,
                           area_bacia_km2=area,fracao_abstracao_inicial=fracao_abstracao_inicial,
                           fonte_cn=fonte_cn,fonte_chuva=fonte_chuva)["escoamento_direto_estimado_mm"]
        delta=q-previous_excess
        if delta<-1e-8:
            raise ErroHidrograma("escoamento acumulado diminuiu")
        dq=max(0.,delta)
        increments.append(dq)
        previous_excess=q
    # Convolution is volume preserving including full recession tail.
    interval_vol=[0.]*(len(increments)+len(weights)-1)
    for i,excess in enumerate(increments):
        volume=excess*area*1000
        for j,w in enumerate(weights):
            interval_vol[i+j]+=volume*w
    seconds=step*3600
    outgoing=[v/seconds for v in interval_vol]
    expected=previous_excess*area*1000
    modeled=fsum(interval_vol)
    if abs(modeled-expected)>max(1e-5,1e-10*max(expected,modeled)):
        raise ErroHidrograma("volume não fecha na convolução")
    start=rain[0][0]
    hydro=[{"data_hora_utc":(start+timedelta(seconds=i*seconds)).isoformat(),
            "vazao_direta_m3_s":flow}
           for i,flow in enumerate(outgoing)]
    return {
        "bacia_id":bacia_id,"passo_horas":step,
        "chuva_total_evento_mm":rain_sum,
        "escoamento_total_estimado_mm":previous_excess,
        "perda_nao_escoada_mm":max(0.,rain_sum-previous_excess),
        "incrementos_excesso_mm":increments,
        "volume_previsto_m3":expected,
        "volume_hidrograma_m3":modeled,
        "erro_conservacao_m3":modeled-expected,
        "vazao_pico_direta_m3_s":max(outgoing),
        "hydrograma":hydro,
        "fonte_chuva":fonte_chuva,"fonte_cn":fonte_cn,
        "fonte_resposta_unitaria":fonte_resposta_unitaria,
        "estado":"MODELO_EVENTO_CN_E_HIDROGRAMA_UNITARIO_SEM_HOMOLOGACAO",
        "limites":"Chuva precisa ser areal (não pluviômetro isolado); CN e "
                 "hidrograma unitário calibrados por bacia; não inclui baseflow, "
                 "afluentes externos, captações nem propagação pela calha principal."}
