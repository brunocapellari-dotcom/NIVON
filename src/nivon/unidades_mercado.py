"""Conversores dimensionais exatos com Decimal.

Esta camada converte unidades físicas/especificações de contrato, não estima
basis, frete, prêmio, preço produtor ou qualquer preço de mercado não observado.
"""
from __future__ import annotations
from decimal import Decimal,InvalidOperation,localcontext
from .qualidade_cientifica import ErroCientifico

LB_KG=Decimal("0.45359237")  # convenção internacional de libra avoirdupois
MASSA_KG={"KG":Decimal("1"),"T":Decimal("1000"),
          "LB":LB_KG,"SHORT_TON":Decimal("2000")*LB_KG}
BUSHEL_LB={
    "SOJA":Decimal("60"),
    "MILHO":Decimal("56"),
    "TRIGO":Decimal("60"),
}
TIPOS_CONTRATO={
    "SOJA":"CBOT_SOYBEANS_60LB_BUSHEL",
    "MILHO":"CBOT_CORN_56LB_BUSHEL",
    "TRIGO":"CBOT_WHEAT_60LB_BUSHEL",
}


def _decimal(v,n):
    if type(v) is bool or not isinstance(v,(str,int,float,Decimal)):
        raise ErroCientifico(f"{n}: número decimal obrigatório")
    try:d=Decimal(str(v))
    except InvalidOperation as exc:raise ErroCientifico(f"{n}: inválido") from exc
    if not d.is_finite() or len(d.as_tuple().digits)>40:
        raise ErroCientifico(f"{n}: não finito ou precisão excessiva")
    return d


def converter_massa(*,valor,unidade_origem:str,unidade_destino:str) -> dict:
    if unidade_origem not in MASSA_KG or unidade_destino not in MASSA_KG:
        raise ErroCientifico("massa deve usar unidade KG/T/LB/SHORT_TON explicitada")
    d=_decimal(valor,"massa")
    if d<0:raise ErroCientifico("massa negativa")
    with localcontext() as ctx:
        ctx.prec=40
        converted=d*MASSA_KG[unidade_origem]/MASSA_KG[unidade_destino]
    return {"valor_decimal":str(converted),"origem":unidade_origem,
            "destino":unidade_destino,"conversao_exata":True}


def referencia_bolsa_cbot_usd_t(*,produto:str,centavos_usd_por_bushel) -> dict:
    if produto not in BUSHEL_LB:raise ErroCientifico("produto sem peso padrão de bushel")
    c=_decimal(centavos_usd_por_bushel,"cotacao_uscent_bu")
    if c<=0:raise ErroCientifico("cotação de grãos deve ser positiva")
    with localcontext() as ctx:
        ctx.prec=40
        quilogramas_por_bushel=BUSHEL_LB[produto]*LB_KG
        usd_bu=c/Decimal("100")
        usd_t=usd_bu*Decimal("1000")/quilogramas_por_bushel
    return {"produto":produto,"contrato":TIPOS_CONTRATO[produto],
            "preco_usd_bushel":str(usd_bu),
            "massa_kg_bushel":str(quilogramas_por_bushel),
            "referencia_usd_t":str(usd_t),
            "status":"CONVERSAO_FISICA_SEM_PRECO_LICENCIADO",
            "limitacao":"Não é paridade, preço produtor nem cotação real; depende de valor de mercado fornecido com direitos"}


def referencia_ice_centavos_libra_usd_t(*,produto:str,centavos_usd_por_libra) -> dict:
    if produto not in {"ACUCAR","ALGODAO"}:
        raise ErroCientifico("contrato ICE lb não validado para este produto")
    cents=_decimal(centavos_usd_por_libra,"cotacao_uscent_lb")
    if cents<=0:raise ErroCientifico("preço físico referencial positivo requerido")
    with localcontext() as ctx:
        ctx.prec=40
        valor=(cents/Decimal("100"))*Decimal("1000")/LB_KG
    return {"produto":produto,"contrato":"ICE_USCENT_LB_CONVERSAO_FISICA",
            "referencia_usd_t":str(valor),
            "status":"CONVERSAO_SEM_IDENTIFICACAO_DE_VENCIMENTO_OU_GRAU",
            "limitacao":"Verificar contrato ICE específico, grade, grau, vencimento e direitos antes de usar"}


def fracao_de_percentual(*,percentual) -> str:
    d=_decimal(percentual,"percentual")
    if not Decimal("0")<=d<=Decimal("100"):
        raise ErroCientifico("percentual fora de 0..100")
    return str(d/Decimal("100"))
