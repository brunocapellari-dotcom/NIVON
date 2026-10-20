"""NIVON: agronometeorologia física, FAO-56 e referência climatológica.

Sem rede ou dados sintéticos implícitos. ETo Penman-Monteith exige RADIAÇÃO
LÍQUIDA medida/derivada previamente; não é a radiação solar incidente.
Seca empírica não é SPI/SPEI, que exigem distribuição e calibração próprias.
"""
from __future__ import annotations
from datetime import date
from math import exp, isfinite
from statistics import mean

class ErroAgrometeo(ValueError):
    pass

def _num(x,n,menor=None,maior=None):
    if type(x) not in (int,float) or not isfinite(x):
        raise ErroAgrometeo(n+" precisa ser número finito, não booleano")
    v=float(x)
    if menor is not None and v<menor or maior is not None and v>maior:
        raise ErroAgrometeo(n+" fora dos limites físicos do motor")
    return v

def _fonte(x):
    if not isinstance(x,str) or len(x.strip())<3 or len(x)>300:
        raise ErroAgrometeo("proveniência de dados/metodologia obrigatória")
    return x

def pressao_saturacao_kpa(temperatura_c):
    t=_num(temperatura_c,"temperatura_c",-50,65)
    return 0.6108*exp(17.27*t/(t+237.3))

def et0_fao56_diaria(*,tmin_c,tmax_c,umidade_min_pct,umidade_max_pct,
                   vento_2m_ms,radiacao_liquida_mj_m2_dia,altitude_m,
                   fluxo_calor_solo_mj_m2_dia=0.0,fonte_radiacao,
                   fonte_meteorologia):
    """FAO-56 (eq. 6) para superfície de referência de grama; mm/dia.

    Vento DEVE ser altura 2m; Rn líquido, não insolação/shortwave bruta.
    Umidade mínima diária pareada a Tmax; RHmax pareada a Tmin.
    """
    tmin=_num(tmin_c,"tmin",-45,60)
    tmax=_num(tmax_c,"tmax",-45,60)
    if tmax<tmin: raise ErroAgrometeo("Tmin superior a Tmax")
    rh_min=_num(umidade_min_pct,"RHmin",0,100)
    rh_max=_num(umidade_max_pct,"RHmax",0,100)
    if rh_min>rh_max: raise ErroAgrometeo("RHmin superior a RHmax")
    u2=_num(vento_2m_ms,"vento_2m",0,35)
    rn=_num(radiacao_liquida_mj_m2_dia,"Rn",-15,45)
    g=_num(fluxo_calor_solo_mj_m2_dia,"G",-15,15)
    z=_num(altitude_m,"altitude",-500,5500)
    _fonte(fonte_radiacao);_fonte(fonte_meteorologia)
    tmean=(tmin+tmax)/2
    es=(pressao_saturacao_kpa(tmin)+pressao_saturacao_kpa(tmax))/2
    ea=(pressao_saturacao_kpa(tmin)*rh_max/100+
        pressao_saturacao_kpa(tmax)*rh_min/100)/2
    deficit=max(0.,es-ea)
    delta=4098*pressao_saturacao_kpa(tmean)/(tmean+237.3)**2
    pressao=101.3*((293-0.0065*z)/293)**5.26
    gamma=0.000665*pressao
    numerador=(0.408*delta*(rn-g)+
               gamma*900/(tmean+273)*u2*deficit)
    denominador=delta+gamma*(1+0.34*u2)
    bruto=numerador/denominador
    if bruto>35:raise ErroAgrometeo("ET0 extrema: rever unidade de Rn, vento, RH e temperatura")
    return {
        "et0_mm_dia":max(0.,bruto),
        "et0_bruta_mm_dia":bruto,
        "clamp_zero_por_saldo_energetico":bruto<0,
        "pressao_atmosferica_kpa":pressao,
        "pressao_vapor_saturacao_kpa":es,
        "pressao_vapor_real_kpa":ea,
        "deficit_pressao_vapor_kpa":deficit,
        "delta_kpa_c":delta,"gamma_kpa_c":gamma,
        "fonte_radiacao":fonte_radiacao,"fonte_meteorologia":fonte_meteorologia,
        "classificacao":"ET0_MODELO_FISICO_FAO56",
        "limite":"ET0 para cultura de referência; não é ETa nem irrigação recomendada. "
                 "Radiação líquida Rn (ondas curtas+longas), vento a 2m, RHmax/RHmin "
                 "e unidade diária precisam ser comprovados; sem QC não promover."
    }

def deficit_hidrico_fenologico(*,et0_mm_dia,kc_cultura,chuva_efetiva_mm,
                            armazenamento_inicial_mm,capacidade_disponivel_mm,
                            fonte_solo_kc,periodo):
    """Balde 1 passo sem capilaridade ou escoamento; ETa limitada à água.

    Sem precipitação efetiva certificada e Kc local, somente simulação.
    """
    et0=_num(et0_mm_dia,"ET0",0,35);kc=_num(kc_cultura,"Kc",0,3)
    chuva=_num(chuva_efetiva_mm,"chuva_efetiva",0,700)
    cap=_num(capacidade_disponivel_mm,"capacidade",0.001,3000)
    inicio=_num(armazenamento_inicial_mm,"agua_inicial",0,cap)
    _fonte(fonte_solo_kc);_fonte(periodo)
    etc=et0*kc
    disponivel=inicio+chuva
    eta=min(etc,disponivel)
    restante=disponivel-eta
    percola=max(0,restante-cap)
    final=min(cap,restante)
    if abs((inicio+chuva)-(eta+percola+final))>1e-8:
        raise ErroAgrometeo("balanço hídrico inconsistente")
    return {"et_cultura_potencial_mm":etc,"et_atendida_mm":eta,
            "deficit_et_mm":etc-eta,
            "estresse_fracao_por_falta_agua":(etc-eta)/etc if etc else 0.,
            "excedente_nao_especificado_mm":percola,
            "armazenamento_final_mm":final,
            "fonte":fonte_solo_kc,"periodo":periodo,
            "classificacao":"CENARIO_BALDE_SEM_PARAMETRO_KS",
            "limite":"Não é coeficiente Ks FAO-56, eficiência de irrigação, "
                     "escoamento medido ou previsão de produtividade."}

def diagnosticar_chuva_climatologica(*,chuva_acumulada_mm,
                                   climatologia_mes_mesma_janela_mm,
                                   amostras_anuais_referencia_mm,
                                   anos_referencia,fonte):
    """Percentil empírico de mesma época do ano, explicitamente NÃO SPI.

    Exige >=30 períodos históricos independentes, um por ano e sem buracos.
    """
    observado=_num(chuva_acumulada_mm,"precipitacao",0,10000)
    normal=_num(climatologia_mes_mesma_janela_mm,"normal",0.001,10000)
    if (not isinstance(amostras_anuais_referencia_mm,(list,tuple)) or
        not isinstance(anos_referencia,(list,tuple)) or
        len(anos_referencia)!=len(amostras_anuais_referencia_mm) or
        len(anos_referencia)<30 or len(anos_referencia)>150):
        raise ErroAgrometeo("mínimo 30 anos históricos alinhados por calendário")
    if any(type(y) is not int or y<1850 or y>2100 for y in anos_referencia):
        raise ErroAgrometeo("ano inválido")
    if any(y2-y1!=1 for y1,y2 in zip(anos_referencia,anos_referencia[1:])):
        raise ErroAgrometeo("série de referência contém lacuna/ordem inválida")
    history=[_num(v,"chuva_historica",0,10000) for v in amostras_anuais_referencia_mm]
    _fonte(fonte)
    less=sum(v<observado for v in history)
    equal=sum(v==observado for v in history)
    percentil=100*(less+equal*.5)/len(history)
    return {"anomalia_percentual":100*(observado/normal-1),
            "percentil_empirico":percentil,
            "anos_validos":len(history),
            "periodo_base_inicio":anos_referencia[0],
            "periodo_base_fim":anos_referencia[-1],
            "fonte":fonte,"classificacao":"PERCENTIL_EMPIRICO_NAO_SPI",
            "limite":"Percentil não é SPI, probabilidade futura, severidade de seca "
                     "do solo ou diagnóstico isolado de perda agrícola; "
                     "precisa de mesma janela sazonal e fontes homogeneizadas."}
