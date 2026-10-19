"""Inteligência temporal e atribuição contábil de movimentos NIVON.

Decomposições são IDENTIDADES matemáticas, não causalidade. Índices mensais
são benchmarks sem vintages as-of e permanecem NÃO HOMOLOGADOS para previsão.
"""
from __future__ import annotations
from datetime import date
from math import isfinite
from .motores import DadoInvalido, numero_positivo


def _n(x,n,zero=False):
    return numero_positivo(x,n,aceita_zero=zero)


def _f(x,n):
    if type(x) not in (int,float) or not isfinite(x):
        raise DadoInvalido(n+": número finito necessário")
    return float(x)


def decompor_mudanca_safra(*,produto,area_anterior_ha,area_atual_ha,
                          rendimento_anterior_kg_ha,rendimento_atual_kg_ha,
                          fonte_metodologia):
    if produto not in ("SOJA","MILHO","ALGODAO","TRIGO","SORGO","CANA","GERGELIM"):
        raise DadoInvalido("safra sem cultura cadastrada")
    a0=_n(area_anterior_ha,"area_anterior")
    a1=_n(area_atual_ha,"area_atual")
    y0=_n(rendimento_anterior_kg_ha,"rendimento_anterior",True)
    y1=_n(rendimento_atual_kg_ha,"rendimento_atual",True)
    if not isinstance(fonte_metodologia,str) or not fonte_metodologia.strip():
        raise DadoInvalido("fonte/metodologia obrigatória")
    inicial=a0*y0/1000
    final=a1*y1/1000
    efeito_area=(a1-a0)*(y0+y1)/2000
    efeito_rendimento=(y1-y0)*(a0+a1)/2000
    return {"produto":produto,"producao_anterior_t":inicial,
            "producao_atual_t":final,"variacao_producao_t":final-inicial,
            "efeito_area_contabil_t":efeito_area,
            "efeito_produtividade_contabil_t":efeito_rendimento,
            "fonte":fonte_metodologia,
            "classificacao":"DECOMPOSICAO_SIMETRICA_CONTABIL",
            "limitacao":"Diferenças de metodologia, revisão, escopo e calendário devem ser conciliadas; efeito matemático não prova causa agronômica."}


def decompor_variacao_preco(*,preco_usd_t_anterior,preco_usd_t_atual,
                           cambio_anterior_rs_usd,cambio_atual_rs_usd,
                           fonte_preco,fonte_cambio):
    p0=_n(preco_usd_t_anterior,"preco_usd_t_anterior")
    p1=_n(preco_usd_t_atual,"preco_usd_t_atual")
    c0=_n(cambio_anterior_rs_usd,"cambio_anterior_rs_usd")
    c1=_n(cambio_atual_rs_usd,"cambio_atual_rs_usd")
    if not isinstance(fonte_preco,str) or not fonte_preco.strip() or not isinstance(fonte_cambio,str) or not fonte_cambio.strip():
        raise DadoInvalido("proveniências de preço e câmbio obrigatórias")
    ef_fx=(c1-c0)*(p0+p1)/2
    ef_preco=(p1-p0)*(c0+c1)/2
    return {"preco_bruto_anterior_rs_t":p0*c0,"preco_bruto_atual_rs_t":p1*c1,
            "variacao_total_rs_t":p1*c1-p0*c0,
            "efeito_cambio_contabil_rs_t":ef_fx,
            "efeito_preco_externo_contabil_rs_t":ef_preco,
            "classificacao":"DECOMPOSICAO_SIMETRICA_SEM_CAUSALIDADE",
            "fonte_preco":fonte_preco,"fonte_cambio":fonte_cambio,
            "limitacao":"Identidade contábil antes de frete, basis, tributos e negociação; não prova transmissão ao produtor."}


def comparar_progresso_safra(*,percentual_atual,percentual_ano_passado,
                            percentual_media_historica,produto,regiao,semana_referencia,fonte):
    vals=[_n(v,n,True) for n,v in (
        ("atual",percentual_atual),("ano_passado",percentual_ano_passado),
        ("media_historica",percentual_media_historica))]
    if any(v>100 for v in vals):
        raise DadoInvalido("progressos devem estar em percentual de 0 a 100")
    if any(not isinstance(x,str) or not x.strip() for x in (produto,regiao,semana_referencia,fonte)):
        raise DadoInvalido("produto, geografia, semana e fonte obrigatórios")
    return {"produto":produto,"regiao":regiao,"semana":semana_referencia,
            "desvio_ano_passado_pontos_percentuais":vals[0]-vals[1],
            "desvio_media_pontos_percentuais":vals[0]-vals[2],
            "fonte":fonte,"classificacao":"COMPARACAO_PROGRESO_PERCENTUAL",
            "limitacao":"Sem as mesmas definições de área, safra, semana e metodologia a comparação é inválida; atraso não implica perda de safra."}


def concentracao_fluxos(*,volumes_por_destino_t,fonte):
    if not isinstance(volumes_por_destino_t,dict) or not volumes_por_destino_t:
        raise DadoInvalido("fluxos por destino vazios")
    valores={}
    for k,v in volumes_por_destino_t.items():
        if not isinstance(k,str) or not k.strip():
            raise DadoInvalido("destino com identificador ausente")
        valores[k]=_n(v,"volume_destino",True)
    total=sum(valores.values())
    if total<=0:
        raise DadoInvalido("não há volume positivo para calcular concentração")
    p={k:v/total for k,v in valores.items()}
    return {"total_t":total,"indice_hhi_fracao":sum(v*v for v in p.values()),
            "maior_destino":max(p,key=p.get),
            "participacao_maior_destino":max(p.values()),
            "fonte":fonte if isinstance(fonte,str) and fonte.strip() else _exigir_fonte(),
            "classificacao":"CONCENTRACAO_RECORTE_OBSERVADO_OU_INFORMADO",
            "limitacao":"HHI de fluxos não equivale risco comercial sem contexto; destinos exigem classificação padronizada e recorte temporal."}


def _exigir_fonte():
    raise DadoInvalido("fonte obrigatória")


def benchmark_sazonal_mensal(*,serie_mensal,fonte,competencia_as_of):
    """Baseline ano anterior vs mês anterior; validação walk-forward LOCAL.

    Só compara meses consecutivos. Exigir séries/vintages reais separados
    antes de declarar modelo promovido.
    """
    if not isinstance(serie_mensal,dict) or len(serie_mensal)<36 or len(serie_mensal)>240:
        raise DadoInvalido("mínimo de 36 e máximo de 240 meses")
    if not isinstance(fonte,str) or not fonte.strip():
        raise DadoInvalido("fonte ausente")
    try:
        corte=date.fromisoformat(competencia_as_of+"-01")
    except (AttributeError,ValueError) as exc:
        raise DadoInvalido("corte mês YYYY-MM obrigatório") from exc
    rows=[]
    for text,valor in serie_mensal.items():
        try: mes=date.fromisoformat(text+"-01")
        except (AttributeError,ValueError) as exc:raise DadoInvalido("mês inválido") from exc
        rows.append((mes,_n(valor,"valor_serie",True)))
    rows.sort()
    if rows[-1][0]>corte:
        raise DadoInvalido("histórico contém mês posterior ao corte as-of")
    for (m0,_),(m1,_) in zip(rows,rows[1:]):
        ano=m0.year+(m0.month//12)
        mes=m0.month%12+1
        if m1!=date(ano,mes,1):
            raise DadoInvalido("lacuna mensal impede baseline sazonal")
    valores=[r[1] for r in rows]
    folds=[]
    for i in range(12,len(rows)):
        real=valores[i]
        sazonal=valores[i-12]
        anterior=valores[i-1]
        folds.append({"mes":rows[i][0].strftime("%Y-%m"),
            "observado":real,"baseline_sazonal":sazonal,
            "baseline_ultimo_mes":anterior})
    es=sum(abs(x["observado"]-x["baseline_sazonal"]) for x in folds)/len(folds)
    en=sum(abs(x["observado"]-x["baseline_ultimo_mes"]) for x in folds)/len(folds)
    return {"meses":len(rows),"folds":len(folds),"mae_sazonal":es,
            "mae_ultimo_mes":en,"sazonal_supera_na_amostra":es<en,
            "fonte":fonte,"competencia_as_of":competencia_as_of,
            "classificacao":"BACKTEST_BASELINE_SEM_VINTAGES",
            "modelo_preditivo_homologado":False,
            "limitacao":"Sem dados de publicação/vintage não mede look-ahead por revisões. Não promete acurácia fora da amostra."}


def custo_diesel_por_rota(*,distancia_ida_km,distancia_volta_km,
                         consumo_l_km_ida,consumo_l_km_volta,
                         diesel_b_rs_l,carga_util_t,fonte):
    ida=_n(distancia_ida_km,"distancia_ida_km",True)
    volta=_n(distancia_volta_km,"distancia_volta_km",True)
    ci=_n(consumo_l_km_ida,"consumo_l_km_ida")
    cv=_n(consumo_l_km_volta,"consumo_l_km_volta")
    valor=_n(diesel_b_rs_l,"diesel_b_rs_l")
    carga=_n(carga_util_t,"carga_util_t")
    total=ida*ci+volta*cv
    if not isinstance(fonte,str) or not fonte.strip():
        raise DadoInvalido("fonte do preço/consumo obrigatória")
    return {"consumo_total_estimado_l":total,"custo_diesel_viagem_rs":total*valor,
            "custo_diesel_rs_t_transportada":total*valor/carga,
            "fonte":fonte,"classificacao":"CENARIO_DIESEL_TRANSPORTE",
            "limitacao":"Consumos por trecho são hipóteses/medições declaradas; não incluem retorno carregado, pedágios, pneus e depreciação."}
