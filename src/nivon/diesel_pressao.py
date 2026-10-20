"""Sensibilidade hipotética de custos rodoviários a preços de diesel.

ANP revenda amostral NÃO é custo de abastecimento contratado de transportadora.
Não estima automaticamente repasse ao frete ou tarifa negociada.
"""
from __future__ import annotations
from decimal import Decimal
from datetime import date


class ErroSensibilidadeDiesel(ValueError):
    pass


def _positivo(valor, campo: str) -> Decimal:
    if not isinstance(valor, Decimal) or not valor.is_finite() or valor <= 0:
        raise ErroSensibilidadeDiesel(f"{campo}: Decimal positivo e finito obrigatório")
    return valor


def _nao_negativo(valor, campo: str) -> Decimal:
    if not isinstance(valor, Decimal) or not valor.is_finite() or valor < 0:
        raise ErroSensibilidadeDiesel(f"{campo}: Decimal não negativo e finito obrigatório")
    return valor


def sensibilidade_diesel(
    *, distancia_operacional_km: Decimal,
    consumo_estimado_l_km: Decimal, carga_por_viagem_t: Decimal,
    preco_diesel_base_brl_l: Decimal, preco_diesel_cenario_brl_l: Decimal,
    distancia_validada: bool, fonte_preco: str, referencia_preco: date,
    produto_diesel: str, premissas_documentadas: bool,
) -> dict:
    """Estima custo de combustível por t, sem atribuir valor real ao frete.

    A distância operacional (rota/retorno documentado) e consumo são
    premissas EXPLICITAS. Volume potencial, oferta e contrato não são
    resultados dessa conta.
    """
    km = _positivo(distancia_operacional_km, "distancia_operacional_km")
    consumo = _positivo(consumo_estimado_l_km, "consumo_estimado_l_km")
    carga = _positivo(carga_por_viagem_t, "carga_por_viagem_t")
    p0 = _positivo(preco_diesel_base_brl_l, "preco_diesel_base_brl_l")
    p1 = _positivo(preco_diesel_cenario_brl_l, "preco_diesel_cenario_brl_l")
    if not distancia_validada or not premissas_documentadas:
        raise ErroSensibilidadeDiesel("distância e premissas precisam de evidência")
    if not isinstance(fonte_preco, str) or not fonte_preco.strip():
        raise ErroSensibilidadeDiesel("fonte do preço obrigatória")
    if not isinstance(referencia_preco, date) or type(referencia_preco) is not date:
        raise ErroSensibilidadeDiesel("referência de preço obrigatória")
    if produto_diesel not in {"DIESEL", "DIESEL_S10"}:
        raise ErroSensibilidadeDiesel("DIESEL e DIESEL_S10 não podem ser misturados")
    if consumo >= Decimal("5") or carga >= Decimal("200") or km >= Decimal("20000"):
        raise ErroSensibilidadeDiesel("premissa fora de limite técnico para revisão")
    litros = km * consumo
    custo_base_t = (litros * p0) / carga
    custo_cenario_t = (litros * p1) / carga
    return {
        "metodo": "CENARIO_CUSTO_COMBUSTIVEL_NAO_FRETE_CONTRATADO",
        "produto_diesel": produto_diesel, "fonte_preco": fonte_preco,
        "referencia_preco": referencia_preco.isoformat(),
        "distancia_operacional_km": str(km),
        "consumo_estimado_l_km": str(consumo),
        "carga_hipotetica_t": str(carga),
        "litros_hipoteticos_por_viagem": str(litros),
        "custo_base_combustivel_brl_t": str(custo_base_t),
        "custo_cenario_combustivel_brl_t": str(custo_cenario_t),
        "variacao_custo_combustivel_brl_t": str(custo_cenario_t - custo_base_t),
        "repasse_ao_frete": "INDETERMINADO",
        "alerta": "Preço de revenda amostral, quando usado, não comprova preço efetivo pago nem volume transportado.",
    }
