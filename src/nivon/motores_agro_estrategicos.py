"""Motores econômicos e industriais por commodity — somente simulações auditáveis.

Não realiza I/O nem busca cotações; variáveis observadas devem entrar com
unidade e proveniência verificadas. Cálculos de preço são REFERÊNCIAS,
não previsão, negociação realizada, preço físico ou paridade homologada.
"""
from __future__ import annotations

from .motores import DadoInvalido, numero_positivo

KG_POR_BUSHEL={"SOJA":27.2155422,"MILHO":25.40117272}
KG_POR_LIBRA=0.45359237
KG_POR_ARROBA_CARCACA=15.0


def _n(x,nome,zero=False):
    return numero_positivo(x,nome,aceita_zero=zero)


def _fonte(x):
    if not isinstance(x,str) or not x.strip():
        raise DadoInvalido("fonte ou hipótese metodológica obrigatória")
    return x


def _fracao(x,nome):
    v=_n(x,nome,True)
    if v>1:
        raise DadoInvalido(nome+": fração acima de 100%")
    return v


def safra_comercializacao(*,produto,area_ha,producao_t,area_colhida_ha,
                         volume_vendido_t,fonte):
    if produto not in ("SOJA","MILHO","ALGODAO","TRIGO","SORGO"):
        raise DadoInvalido("produto fora do módulo safra")
    area=_n(area_ha,"area_ha")
    producao=_n(producao_t,"producao_t",True)
    colhida=_n(area_colhida_ha,"area_colhida_ha",True)
    vendida=_n(volume_vendido_t,"volume_vendido_t",True)
    if colhida>area or vendida>producao:
        raise DadoInvalido("colheita ou vendas acima do denominador informado")
    return {"produto":produto,"produtividade_kg_ha":1000*producao/area,
            "percentual_area_colhida":100*colhida/area,
            "percentual_producao_comercializada":100*vendida/producao if producao else None,
            "fonte":_fonte(fonte),"classificacao":"INDICADORES_DERIVADOS",
            "limitacao":"Comercialização não é embarque físico; colheita por área não é produção realizada."}


def referencia_futuros_graos(*,produto,usd_por_bushel,cambio_rs_usd,
                            ajuste_base_usd_t,frete_mais_custos_rs_t,fonte):
    """Conversão de preço CBOT de soja/milho; basis e custos são HIPÓTESES explícitas."""
    if produto not in KG_POR_BUSHEL:
        raise DadoInvalido("conversão bushel não homologada para o produto")
    futuro=_n(usd_por_bushel,"usd_por_bushel")
    cambio=_n(cambio_rs_usd,"cambio_rs_usd")
    if isinstance(ajuste_base_usd_t,bool) or not isinstance(ajuste_base_usd_t,(float,int)):
        raise DadoInvalido("basis explícito, pode ser negativo")
    from math import isfinite
    if not isfinite(ajuste_base_usd_t):
        raise DadoInvalido("basis não finito")
    bruto=(futuro*1000/KG_POR_BUSHEL[produto]+ajuste_base_usd_t)*cambio
    custo=_n(frete_mais_custos_rs_t,"frete_mais_custos_rs_t",True)
    return {"produto":produto,"benchmark_rs_t":bruto-custo,
            "benchmark_rs_saca_60kg":(bruto-custo)*.06,
            "fonte":_fonte(fonte),"classificacao":"CENARIO_FUTUROS_COM_BASIS",
            "limitacao":"Futuro CBOT + basis hipotético não é FOB verificado nem preço pago ao produtor."}


def esmagamento_soja(*,soja_t,rendimento_farelo,rendimento_oleo,
                     rendimento_outros_e_perdas,fonte):
    soja=_n(soja_t,"soja_t")
    f=_fracao(rendimento_farelo,"rendimento_farelo")
    o=_fracao(rendimento_oleo,"rendimento_oleo")
    r=_fracao(rendimento_outros_e_perdas,"rendimento_outros_e_perdas")
    if abs(f+o+r-1)>1e-8:
        raise DadoInvalido("balanço de soja esmagada não fecha")
    return {"soja_processada_t":soja,"farelo_t":soja*f,
            "oleo_t":soja*o,"outros_e_perdas_t":soja*r,
            "fonte":_fonte(fonte),"classificacao":"SIMULACAO_BALANCO_ESMAGAMENTO",
            "limitacao":"Produção derivada não se soma à soja como oferta adicional."}


def milho_safras_demanda(*,primeira_t,segunda_t,terceira_t,
                        total_oficial_t,consumo_interno_total_t,
                        consumo_racao_parcela_t,consumo_industrial_parcela_t,fonte):
    partes=[_n(v,str(i),True) for i,v in enumerate((primeira_t,segunda_t,terceira_t))]
    total=_n(total_oficial_t,"total_oficial_t",True)
    interno=_n(consumo_interno_total_t,"consumo_interno_total_t",True)
    racao=_n(consumo_racao_parcela_t,"racao",True)
    industria=_n(consumo_industrial_parcela_t,"industria",True)
    if racao+industria>interno+1e-6:
        raise DadoInvalido("consumo ração e indústria excedem total; risco de dupla contagem")
    return {"producao_soma_safras_t":sum(partes),"producao_oficial_t":total,
            "diferenca_total_oficial_t":total-sum(partes),
            "consumo_interno_total_t":interno,"racao_parcela_t":racao,
            "industria_parcela_t":industria,"outros_usos_t":max(0.,interno-racao-industria),
            "fonte":_fonte(fonte),"classificacao":"CONFERENCIA_BALANCO_SEM_DUPLA_CONTAGEM"}


def algodao_beneficiamento(*,algodao_em_caroco_t,fracao_pluma,
                          fracao_caroco,fracao_residuos_perdas,fonte):
    entrada=_n(algodao_em_caroco_t,"algodao_em_caroco_t")
    partes=[_fracao(x,n) for n,x in (("pluma",fracao_pluma),("caroco",fracao_caroco),
                                     ("residuos",fracao_residuos_perdas))]
    if abs(sum(partes)-1)>1e-8:
        raise DadoInvalido("pluma/caroço/resíduo devem conciliar massa")
    return {"entrada_algodao_caroco_t":entrada,"pluma_t":entrada*partes[0],
            "caroco_semente_t":entrada*partes[1],"residuos_perdas_t":entrada*partes[2],
            "fonte":_fonte(fonte),"classificacao":"BALANCO_INDUSTRIAL_HIPOTETICO",
            "limitacao":"Algodão em caroço, pluma e caroço de algodão têm mercados físicos distintos."}


def boi_rendimento_carcaca(*,cabecas_abatidas,peso_vivo_medio_kg,
                          rendimento_carcaca,preco_rs_arroba,fonte):
    n=_n(cabecas_abatidas,"cabecas_abatidas")
    if not n.is_integer():
        raise DadoInvalido("abate exige cabeças inteiras")
    vivo=_n(peso_vivo_medio_kg,"peso_vivo_medio_kg")
    rend=_fracao(rendimento_carcaca,"rendimento_carcaca")
    if rend==0:
        raise DadoInvalido("rendimento de carcaça zero")
    pr=_n(preco_rs_arroba,"preco_rs_arroba")
    carc=vivo*rend
    return {"cabecas":int(n),"peso_carcaca_estimado_kg_cabeca":carc,
            "carcaca_total_estimada_t":carc*n/1000,
            "arrobas_carcaca_cabeca":carc/KG_POR_ARROBA_CARCACA,
            "valor_bruto_hipotetico_rs_cabeca":carc/KG_POR_ARROBA_CARCACA*pr,
            "fonte":_fonte(fonte),"classificacao":"CENARIO_RENDIMENTO_BOVINO",
            "limitacao":"Preço arroba da carcaça; não é preço por kg vivo, lucro ou total da produção estadual."}


def relacao_troca_bezerro(*,preco_bezerro_rs_cabeca,
                         preco_boi_rs_arroba,peso_carcaca_boi_kg,fonte):
    bezerro=_n(preco_bezerro_rs_cabeca,"preco_bezerro")
    boi=_n(preco_boi_rs_arroba,"preco_boi")
    carc=_n(peso_carcaca_boi_kg,"peso_carcaca_boi_kg")
    return {"bezerros_por_valor_bruto_boi":(boi*carc/15)/bezerro,
            "fonte":_fonte(fonte),"classificacao":"RELACAO_TROCA_BRUTA_HIPOTETICA",
            "limitacao":"Não desconta recria, engorda, mortalidade, frete e impostos."}


def referencia_acucar_ice(*,centavos_usd_libra,cambio_rs_usd,
                         basis_usd_t,custos_rs_t,fonte):
    pr=_n(centavos_usd_libra,"centavos_usd_libra")/100
    fx=_n(cambio_rs_usd,"cambio_rs_usd")
    from math import isfinite
    if type(basis_usd_t) not in (int,float) or not isfinite(basis_usd_t):
        raise DadoInvalido("basis de açúcar explícito obrigatório")
    custos=_n(custos_rs_t,"custos_rs_t",True)
    base=(pr*1000/KG_POR_LIBRA+basis_usd_t)*fx
    return {"ice_referencia_usd_t":pr*1000/KG_POR_LIBRA,
            "cenario_liquido_rs_t":base-custos,
            "fonte":_fonte(fonte),"classificacao":"CENARIO_ICE_11_COM_BASIS",
            "limitacao":"ICE 11 não equivale a cotação física ou venda de açúcar brasileiro."}


def paridade_importacao_trigo(*,fob_usd_t,frete_maritimo_usd_t,
                             seguro_usd_t,cambio_rs_usd,tributos_rs_t,
                             porto_e_frete_interno_rs_t,fonte):
    cif=(_n(fob_usd_t,"fob")+_n(frete_maritimo_usd_t,"frete",True)+
         _n(seguro_usd_t,"seguro",True))
    landed=cif*_n(cambio_rs_usd,"cambio")+_n(tributos_rs_t,"tributos",True)+_n(porto_e_frete_interno_rs_t,"porto_frete",True)
    return {"cif_usd_t":cif,"custo_posto_destino_rs_t":landed,
            "fonte":_fonte(fonte),"classificacao":"CENARIO_PARIDADE_TRIGO",
            "limitacao":"Qualidade, alíquota, origem, porto e câmbio reais devem ser fornecidos."}


def sorgo_substituicao_racao(*,milho_substituido_t,preco_milho_rs_t,
                           preco_sorgo_rs_t,fracao_substituivel_validada,fonte):
    quantidade=_n(milho_substituido_t,"milho_substituido_t",True)
    frac=_fracao(fracao_substituivel_validada,"fracao_substituivel_validada")
    economia=quantidade*frac*(_n(preco_milho_rs_t,"preco_milho")-_n(preco_sorgo_rs_t,"preco_sorgo"))
    return {"sorgo_substituido_t":quantidade*frac,
            "economia_insumos_rs":economia,"fonte":_fonte(fonte),
            "classificacao":"CENARIO_SUBSTITUICAO_RACAO",
            "limitacao":"A fração precisa ser validada nutricionalmente por espécie/fase e não prova uso observado."}


def paridade_fertilizante(*,produto,fob_usd_t,frete_usd_t,seguro_usd_t,
                         cambio_rs_usd,tributos_rs_t,porto_rs_t,frete_interno_rs_t,fonte):
    if produto not in ("UREIA","MAP","DAP","KCL"):
        raise DadoInvalido("fertilizante sem produto canônico")
    cif=sum(_n(v,k,True) for k,v in (("fob",fob_usd_t),("frete",frete_usd_t),("seguro",seguro_usd_t)))
    if cif<=0:
        raise DadoInvalido("CIF zero")
    valor=cif*_n(cambio_rs_usd,"cambio")+sum(_n(v,k,True) for k,v in (
        ("tributos",tributos_rs_t),("porto",porto_rs_t),("frete_interno",frete_interno_rs_t)))
    return {"produto":produto,"cif_usd_t":cif,"custo_importado_posto_rs_t":valor,
            "fonte":_fonte(fonte),"classificacao":"CENARIO_PARIDADE_IMPORTACAO",
            "limitacao":"Preço da formulação física, não R$/kg nutriente ou preço efetivo de entrega."}


def paridade_diesel(*,diesel_a_usd_t,cambio_rs_usd,densidade_diesel_a_kg_l,
                   custos_diesel_a_rs_l,preco_biodiesel_rs_l,fracao_biodiesel,
                   tributos_margens_b_rs_l,preco_observado_diesel_b_rs_l,fonte):
    diesel=_n(diesel_a_usd_t,"diesel_a_usd_t")
    fx=_n(cambio_rs_usd,"cambio")
    dens=_n(densidade_diesel_a_kg_l,"densidade")
    if dens>1.1:
        raise DadoInvalido("densidade deve ser kg/L, não kg/m3")
    mix=_fracao(fracao_biodiesel,"mistura_biodiesel")
    a=diesel*dens/1000*fx+_n(custos_diesel_a_rs_l,"custos_diesel_a",True)
    b=a*(1-mix)+_n(preco_biodiesel_rs_l,"biodiesel",True)*mix+_n(tributos_margens_b_rs_l,"tributos_margens",True)
    obs=_n(preco_observado_diesel_b_rs_l,"preco_observado_diesel_b")
    return {"referencia_diesel_a_rs_l":a,"referencia_diesel_b_rs_l":b,
            "diferenca_observado_menos_referencia_rs_l":obs-b,
            "fonte":_fonte(fonte),"classificacao":"CENARIO_PARIDADE_DIESEL_B",
            "limitacao":"Requer referência internacional de diesel A, mistura vigente, densidade, tributos e margens; petróleo Brent não substitui preço diesel."}


def simulacao_etanol_ddg(*,milho_processado_t,litros_etanol_por_t,
                        ddg_kg_por_t,oleo_l_por_t,fonte_coeficientes):
    milho=_n(milho_processado_t,"milho_processado_t")
    et=_n(litros_etanol_por_t,"litros_etanol_por_t")
    ddg=_n(ddg_kg_por_t,"ddg_kg_por_t",True)
    oleo=_n(oleo_l_por_t,"oleo_l_por_t",True)
    return {"milho_t":milho,"etanol_l":milho*et,"ddg_kg":milho*ddg,
            "oleo_milho_l":milho*oleo,"fonte":_fonte(fonte_coeficientes),
            "classificacao":"CENARIO_COEFICIENTES_NAO_BALANCO_FISICO",
            "limitacao":"Coeficientes podem ser economicamente úteis mas fisicamente inconsistentes. Validar massa seca e tipo de etanol separadamente."}
