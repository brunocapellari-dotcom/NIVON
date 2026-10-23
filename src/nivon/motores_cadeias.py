"""Cenários quantitativos das cadeias CANA/GERGELIM/FRANGO/SUINO.

Funções puras sem rede: entradas e coeficientes explícitos; não são
observações reais, cotações, previsões validadas ou lucro garantido.
"""
from __future__ import annotations
from datetime import datetime
from .motores import DadoInvalido, numero_positivo, projetar_consumo
from .previsoes import avaliar_crescimento_anual


def _n(v, nome, zero=False):
    return numero_positivo(v, nome, aceita_zero=zero)


def simular_atr_cana(*, cana_moida_t, atr_kg_t, fracao_acucar,
                    fracao_etanol, fonte_parametros):
    cana=_n(cana_moida_t,"cana_moida_t")
    atr=_n(atr_kg_t,"atr_kg_t")
    a=_n(fracao_acucar,"fracao_acucar",True)
    e=_n(fracao_etanol,"fracao_etanol",True)
    if atr > 1000 or a>1 or e>1 or abs(a+e-1)>1e-9:
        raise DadoInvalido("frações industriais ou ATR incompatíveis")
    if not isinstance(fonte_parametros,str) or not fonte_parametros.strip():
        raise DadoInvalido("fonte ATR/mix obrigatória")
    total=cana*atr
    return {"cana_moida_t":cana,"atr_total_kg":total,
            "atr_alocado_acucar_kg":total*a,"atr_alocado_etanol_kg":total*e,
            "classificacao":"CENARIO_ATR_ALOCADO","fonte_parametros":fonte_parametros,
            "limitacao":"ATR destinado não mede produção final de açúcar em t ou etanol em L."}


def paridade_gergelim(*, fob_usd_t, cambio_rs_usd, frete_rs_t, porto_rs_t,
                      outros_rs_t, fonte_fob, fonte_cambio):
    bruto=_n(fob_usd_t,"fob_usd_t")*_n(cambio_rs_usd,"cambio_rs_usd")
    custos=(_n(frete_rs_t,"frete_rs_t",True)+_n(porto_rs_t,"porto_rs_t",True)
            +_n(outros_rs_t,"outros_rs_t",True))
    if any(not isinstance(x,str) or not x.strip() for x in (fonte_fob,fonte_cambio)):
        raise DadoInvalido("fonte do preço e câmbio obrigatórias")
    return {"equivalente_fob_rs_t":bruto,"custos_informados_rs_t":custos,
            "paridade_liquida_rs_t":bruto-custos,
            "classificacao":"CENARIO_PARIDADE_EXPORTACAO",
            "fonte_fob":fonte_fob,"fonte_cambio":fonte_cambio,
            "limitacao":"Não equivale a preço recebido pelo produtor ou negociação realizada."}


def margem_proteina(*, especie, preco_vivo_rs_kg, conversao_racao_kg_kg_ganho,
                    fracoes_ingredientes, precos_ingredientes_rs_t,
                    outros_custos_rs_kg_ganho, fonte_parametros):
    if especie not in ("FRANGO","SUINO"):
        raise DadoInvalido("espécie fora do contrato")
    if (not isinstance(fracoes_ingredientes,dict) or not fracoes_ingredientes
            or not isinstance(precos_ingredientes_rs_t,dict)
            or set(fracoes_ingredientes)!=set(precos_ingredientes_rs_t)):
        raise DadoInvalido("formulação/preço incompletos")
    soma,custo_t=0.,0.
    for k,x in fracoes_ingredientes.items():
        if not isinstance(k,str) or not k.strip():
            raise DadoInvalido("ingrediente sem identificador")
        frac=_n(x,f"fracao_{k}",True)
        soma+=frac
        custo_t+=frac*_n(precos_ingredientes_rs_t[k],f"preco_{k}",True)
    if abs(soma-1)>1e-9:
        raise DadoInvalido("frações de massa da ração devem somar um")
    fcr=_n(conversao_racao_kg_kg_ganho,"conversao_racao")
    preco=_n(preco_vivo_rs_kg,"preco_vivo_rs_kg")
    outros=_n(outros_custos_rs_kg_ganho,"outros_custos",True)
    if not isinstance(fonte_parametros,str) or not fonte_parametros.strip():
        raise DadoInvalido("fonte da conversão/formulação obrigatória")
    racao=custo_t/1000*fcr
    return {"especie":especie,"custo_racao_rs_t":custo_t,
            "custo_racao_rs_kg_ganho":racao,
            "margem_contribuicao_rs_kg_ganho":preco-racao-outros,
            "classificacao":"SIMULACAO_MARGEM_NAO_OBSERVADA",
            "fonte_parametros":fonte_parametros,
            "limitacao":"Hipótese sobre kg de ganho vivo, não rendimento de carcaça, lucro líquido ou margem do frigorífico."}


def peso_medio_carcaca(*, especie, cabecas, peso_carcacas_kg):
    if especie not in ("FRANGO","SUINO"):
        raise DadoInvalido("espécie inválida")
    n=_n(cabecas,"cabecas")
    if not n.is_integer():
        raise DadoInvalido("cabeças fracionárias")
    return {"especie":especie,"peso_medio_kg_cabeca":_n(peso_carcacas_kg,"peso_carcacas_kg")/n,
            "classificacao":"DERIVADO_ABATE_INSPECIONADO"}


def intensidade_exportacao_carne(*, especie, exportacao_carcaca_equiv_t,
                                 producao_carcaca_equiv_t, fonte_conversao,
                                 calendario, competencia):
    if especie not in ("FRANGO","SUINO") or calendario not in ("ANO_CIVIL","TRIMESTRE","MES"):
        raise DadoInvalido("espécie/período inválido")
    if not isinstance(competencia,str) or not competencia.strip():
        raise DadoInvalido("competência ausente")
    if not isinstance(fonte_conversao,str) or not fonte_conversao.strip():
        raise DadoInvalido("conversão equivalente-carcaça não documentada")
    p=_n(producao_carcaca_equiv_t,"producao_carcaca_equiv_t")
    e=_n(exportacao_carcaca_equiv_t,"exportacao_carcaca_equiv_t",True)
    return {"especie":especie,"competencia":competencia,"calendario":calendario,
            "razao_exportacao_producao":e/p,"exportacao_maior_que_producao":e>p,
            "classificacao":"RAZAO_INDICATIVA_SEM_BALANCO_COMPLETO",
            "fonte_conversao":fonte_conversao,
            "limitacao":"Razão não é participação exportada se houver estoques ou cobertura diferente."}


def cenario_anual(*, produto, historico, janela=3, horizonte=2):
    if produto not in ("CANA","GERGELIM","FRANGO","SUINO"):
        raise DadoInvalido("cadeia não suportada")
    r=projetar_consumo(historico,janela=janela,horizonte=horizonte)
    return {"produto":produto,**r,"validado_com_dados_reais":False}


def backtest_anual(*, produto, historico, janela=3):
    if produto not in ("CANA","GERGELIM","FRANGO","SUINO"):
        raise DadoInvalido("cadeia não suportada")
    return {"produto":produto,**avaliar_crescimento_anual(historico,janela=janela)}


FATORES={
    "CANA":{"CLIMA","QUEIMADA","MIX_INDUSTRIAL","COMERCIO","ENERGIA"},
    "GERGELIM":{"CLIMA","LOGISTICA","PRECO_CAMBIO","COMERCIO"},
    "FRANGO":{"SANITARIO","RACAO","CLIMA","COMERCIO","LOGISTICA"},
    "SUINO":{"SANITARIO","RACAO","CLIMA","COMERCIO","LOGISTICA"},
}


def classificar_risco(*, produto, fator, evidencia, fonte_id, publicado_em, competencia):
    if produto not in FATORES or fator not in FATORES[produto]:
        raise DadoInvalido("fator incompatível com cadeia")
    if evidencia not in ("CONFIRMADO","ESTIMADO","ALERTA_NAO_CONFIRMADO"):
        raise DadoInvalido("evidência inválida")
    if not isinstance(fonte_id,str) or not fonte_id.strip() or not isinstance(competencia,str) or not competencia.strip():
        raise DadoInvalido("fonte/competência ausente")
    try:
        dt=datetime.fromisoformat(publicado_em.replace("Z","+00:00"))
    except (AttributeError, ValueError) as exc:
        raise DadoInvalido("publicação inválida") from exc
    if dt.tzinfo is None:
        raise DadoInvalido("fuso de publicação obrigatório")
    return {"produto":produto,"fator":fator,"evidencia":evidencia,
            "fonte_id":fonte_id,"publicado_em":publicado_em,
            "competencia":competencia,"classificacao":"SINAL_QUALITATIVO",
            "probabilidade":None,
            "limitacao":"Sem calibração não inferir score quantitativo nem impacto financeiro."}
