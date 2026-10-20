"""NIVON: matemática física e estatística; adaptação metodológica, sem dados sintéticos em produção.

FAO-56 Penman-Monteith: inputs já reduzidos nas grandezas físicas especificadas;
NSE e KGE-2009: pares de vazão observada e simulada no mesmo local/intervalo;
balanço animal: categorias canônicas sem inferir disponibilidade de abate.
"""
from __future__ import annotations
from math import exp, isfinite, sqrt
from .qualidade_cientifica import ErroCientifico, numero


def eto_fao56_penman_monteith(
    *, temperatura_media_c: float, radiacao_liquida_mj_m2_dia: float,
    fluxo_calor_solo_mj_m2_dia: float, vento_2m_m_s: float,
    vapor_saturacao_kpa: float, vapor_real_kpa: float,
    declive_vapor_kpa_c: float, constante_psicrometrica_kpa_c: float,
    referencia_fonte: str,
) -> dict:
    """ET0, mm/d; todos os insumos meteorológicos devem referir o mesmo dia/local.

    FAO-56: (0.408 Delta (Rn-G) + gamma * 900/(T+273) * u2 * (es-ea))
            / (Delta + gamma*(1+0.34*u2)).
    Vapor de saturação e real em kPa; vento a 2m; radiação MJ/m²/d.
    """
    if not isinstance(referencia_fonte,str) or not referencia_fonte.strip():
        raise ErroCientifico("origem dos insumos meteorológicos obrigatória")
    t = numero(temperatura_media_c, "temperatura_media_c", nao_negativo=False)
    rn = numero(radiacao_liquida_mj_m2_dia,"radiacao_liquida",nao_negativo=False)
    g = numero(fluxo_calor_solo_mj_m2_dia,"fluxo_solo",nao_negativo=False)
    u = numero(vento_2m_m_s,"vento_2m_m_s")
    es = numero(vapor_saturacao_kpa,"vapor_saturacao")
    ea = numero(vapor_real_kpa,"vapor_real")
    delta = numero(declive_vapor_kpa_c,"declive_vapor")
    gamma = numero(constante_psicrometrica_kpa_c,"constante_psicrometrica")
    if t <= -273 or delta <= 0 or gamma <= 0 or ea > es or es == 0:
        raise ErroCientifico("parâmetros FAO-56 termodinâmicos inconsistentes")
    denominador = delta + gamma*(1+0.34*u)
    radiativo = 0.408*delta*(rn-g)
    aerodinamico = gamma*900/(t+273)*u*(es-ea)
    et0 = (radiativo+aerodinamico)/denominador
    if not isfinite(et0) or et0 < 0:
        raise ErroCientifico("ET0 negativa ou não finita: investigar insumos, não truncar")
    return {"eto_mm_dia":et0,"numerador_radiativo":radiativo,
            "numerador_aerodinamico":aerodinamico,
            "metodo":"FAO56_PENMAN_MONTEITH_DIARIO", "fonte_insumos":referencia_fonte,
            "status":"CALCULO_FISICO_NAO_VALIDACAO_LOCAL",
            "limitacao":"Exige radiação, vapor, vento e temperatura homogêneos; Kc/ETc e irrigação não inferidos"}


def avaliar_vazao_hidrologica(*, observada_m3_s, prevista_m3_s,
                             identificador_estacao: str,
                             intervalo: str) -> dict:
    """NSE e KGE2009, sem substituir NaN, suavizar negativos nem normalizar dados."""
    if not identificador_estacao or not intervalo:
        raise ErroCientifico("estação e intervalo são obrigatórios")
    if not isinstance(observada_m3_s,(list,tuple)) or not isinstance(prevista_m3_s,(list,tuple)):
        raise ErroCientifico("séries de vazão devem ser sequências explícitas")
    if len(observada_m3_s)!=len(prevista_m3_s) or len(observada_m3_s)<10:
        raise ErroCientifico("pelo menos 10 pares alinhados de vazão")
    obs=[numero(x,"vazao_observada") for x in observada_m3_s]
    pred=[numero(x,"vazao_prevista") for x in prevista_m3_s]
    n=len(obs)
    mo=sum(obs)/n; mp=sum(pred)/n
    ss_o=sum((x-mo)**2 for x in obs)
    ss_p=sum((x-mp)**2 for x in pred)
    if ss_o == 0 or ss_p == 0 or mo <= 0:
        raise ErroCientifico("KGE/NSE indefinido para série observada ou previsão sem variabilidade, ou vazão média zero")
    cov=sum((x-mo)*(y-mp) for x,y in zip(obs,pred))
    r=cov/sqrt(ss_o*ss_p)
    alpha=sqrt(ss_p/ss_o)
    beta=mp/mo
    kge=1-sqrt((r-1)**2+(alpha-1)**2+(beta-1)**2)
    nse=1-sum((x-y)**2 for x,y in zip(obs,pred))/ss_o
    pbias=100*(sum(pred)-sum(obs))/sum(obs)
    return {"estacao":identificador_estacao,"intervalo":intervalo,"pares":n,
            "nse":nse,"kge_2009":kge,"correlacao_r":r,
            "razao_variabilidade_alpha":alpha,"razao_media_beta":beta,
            "vies_percentual_predito_menos_observado":pbias,
            "status":"BACKTEST_HIDRO_ESTADISTICO_NAO_HOMOLOGADO",
            "limitacao":"Não confirma calado, navegabilidade, datum de régua nem skill fora da amostra"}


def reconciliar_rebanho(
    *, especie: str, categoria: str, estoque_inicial_cabecas: int,
    nascimentos_cabecas: int, compras_cabecas: int, transferencias_entrada_cabecas: int,
    mortes_cabecas: int, vendas_cabecas: int, abate_cabecas: int,
    transferencias_saida_cabecas: int, estoque_final_reportado_cabecas: int,
) -> dict:
    """Movimento contábil declarado, não modelo biológico; valida balanço por coorte.

    Uma transferência entre duas categorias gera saída/entrada em categorias distintas
    e deve ser conciliada pelo agregado em camada acima. Abate e vendas não duplicados.
    """
    if especie not in {"BOVINO","SUINO","FRANGO"}:
        raise ErroCientifico("espécie não cadastrada")
    if not isinstance(categoria,str) or not categoria.strip():
        raise ErroCientifico("categoria necessária")
    labels={
        "estoque_inicial":estoque_inicial_cabecas,"nascimentos":nascimentos_cabecas,
        "compras":compras_cabecas,"transferencias_entrada":transferencias_entrada_cabecas,
        "mortes":mortes_cabecas,"vendas":vendas_cabecas,"abate":abate_cabecas,
        "transferencias_saida":transferencias_saida_cabecas,
        "estoque_final_reportado":estoque_final_reportado_cabecas,
    }
    for k,v in labels.items():
        if type(v) is not int or v<0:
            raise ErroCientifico(f"{k}: contagem inteira não negativa exigida")
    calculado=(estoque_inicial_cabecas+nascimentos_cabecas+compras_cabecas+
               transferencias_entrada_cabecas-mortes_cabecas-vendas_cabecas-
               abate_cabecas-transferencias_saida_cabecas)
    if calculado < 0:
        raise ErroCientifico("saídas excedem disponibilidade física da coorte")
    return {"especie":especie,"categoria":categoria,"estoque_final_calculado_cabecas":calculado,
            "residuo_cabecas":estoque_final_reportado_cabecas-calculado,
            "consistente":calculado==estoque_final_reportado_cabecas,
            "status":"IDENTIDADE_REBANHO_NAO_MODELO_BIOLOGICO",
            "limitacao":"IBGE PPM é estoque estimado anual; abate inspecionado é fluxo de cobertura distinta"}
