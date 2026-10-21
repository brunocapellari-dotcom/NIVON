"""Dinâmica DESCRITIVA do movimento: força, perda de força, reversão.

Compara duas janelas DISJUNTAS da mesma série econômica e mesma edição as-of.
Sem extrapolação, previsão de preço, percentual de acerto ou probabilidade.
A série precisa ter passado pelo controle setorial (identidade, lote, contrato,
fonte, licença, calendário de pregão) antes de chegar a esta função.
"""
from __future__ import annotations

from typing import Mapping, Sequence

from .motor_tendencias import (
    ErroTendencia, _numero, tendencia_observada,
)


def comparar_forca_tendencia(
    serie: Sequence[Mapping], *, as_of: str, fonte_id: str, unidade: str,
    frequencia: str, janela: int = 6,
    tolerancia_absoluta: float = 0.0,
    tolerancia_relativa: float = 0.0,
    mudanca_minima_forca_em_limiares: float = 1.0,
    nao_negativo: bool = True,
) -> dict:
    """Compara duas janelas recentes de igual extensão, SEM sobreposição.

    Força = abs(deslocamento descritivo Theil–Sen) / limiar do indicador.
    Sua diferença é uma variação adimensional da amplitude em unidades
    da banda comercial declarada. NÃO mede aceleração física/derivada segunda,
    causalidade, significância estatística ou direção futura.

    Retorna INDETERMINADA quando alguma das janelas não suporta direção
    estável; exige sempre 2*janela pontos e mesma frequência ao longo de
    toda a série. Para calendário de sessões, QC externo permanece necessário.
    """
    if type(janela) is not int or not 4 <= janela <= 48:
        raise ErroTendencia("janela deve ter 4 a 48 observações")
    limite = _numero(
        mudanca_minima_forca_em_limiares, "mudanca_minima_forca_em_limiares",
        nao_negativo=True,
    )
    if limite <= 0 or limite > 100:
        raise ErroTendencia("mudança mínima de força deve ser positiva e <= 100 bandas")
    if not isinstance(serie, (list, tuple)) or len(serie) > 240:
        raise ErroTendencia("série inválida ou excessiva")
    if len(serie) < 2 * janela:
        return {
            "status": "DADOS_INSUFICIENTES",
            "orientacao": "OBSERVADA", "dinamica": "INDETERMINADA",
            "tendencia_atual": "INDETERMINADA",
            "necessarias": 2 * janela, "disponiveis": len(serie),
            "probabilidades_calibradas": None, "publicavel": False,
        }
    config = {
        "as_of": as_of, "fonte_id": fonte_id, "unidade": unidade,
        "frequencia": frequencia, "janela": janela,
        "tolerancia_absoluta": tolerancia_absoluta,
        "tolerancia_relativa": tolerancia_relativa,
        "nao_negativo": nao_negativo,
    }
    # O cálculo sobre a série INTEIRA detecta duplicidades, lacunas e
    # inconsistências justamente na fronteira das duas janelas.
    validado = tendencia_observada(serie, **config)
    if validado["status"] != "DESCRITIVO_OFFLINE_NAO_HOMOLOGADO":
        raise ErroTendencia("série não validada pelo motor descritivo")
    anterior = tendencia_observada(serie[-2*janela:-janela], **config)
    atual = tendencia_observada(serie[-janela:], **config)

    ta, tb = anterior["tendencia"], atual["tendencia"]
    fa = abs(anterior["deslocamento_descritivo"]) / anterior["limiar_unidade"]
    fb = abs(atual["deslocamento_descritivo"]) / atual["limiar_unidade"]
    diferenca = fb - fa

    if "INDETERMINADA" in (ta, tb):
        dinamica = "INDETERMINADA"
    elif ta == tb == "ESTABILIDADE":
        dinamica = "ESTABILIDADE_PERSISTENTE"
    elif ta in ("ALTA", "BAIXA") and tb in ("ALTA", "BAIXA") and ta != tb:
        dinamica = "REVERSAO_OBSERVADA"
    elif ta == "ESTABILIDADE" and tb in ("ALTA", "BAIXA"):
        dinamica = "SAIDA_DA_ESTABILIDADE"
    elif tb == "ESTABILIDADE" and ta in ("ALTA", "BAIXA"):
        dinamica = "ENTRADA_EM_ESTABILIDADE"
    elif diferenca >= limite:
        dinamica = "AUMENTO_DE_FORCA"
    elif diferenca <= -limite:
        dinamica = "PERDA_DE_FORCA"
    else:
        dinamica = "FORCA_SEM_ALTERACAO_RELEVANTE"

    return {
        "status": "DINAMICA_DESCRITIVA_OFFLINE_NAO_HOMOLOGADA",
        "orientacao": "OBSERVADA", "dinamica": dinamica,
        "tendencia_anterior": ta, "tendencia_atual": tb,
        "janela_anterior": [
            anterior["periodo_inicial"], anterior["periodo_final"]
        ],
        "janela_atual": [atual["periodo_inicial"], atual["periodo_final"]],
        "janela_observacoes": janela,
        "metodo": "THEIL_SEN_JANELAS_DISJUNTAS_COMPARACAO_BANDAS",
        "forca_anterior_em_limiares": fa,
        "forca_atual_em_limiares": fb,
        "variacao_forca_em_limiares": diferenca,
        "mudanca_minima_forca_em_limiares": limite,
        "limiar_anterior_unidade": anterior["limiar_unidade"],
        "limiar_atual_unidade": atual["limiar_unidade"],
        "frequencia": frequencia, "unidade": unidade,
        "fonte_id": fonte_id, "as_of": as_of,
        "probabilidades_calibradas": None, "publicavel": False,
        "limitacao": (
            "Mudança histórica de amplitude por banda, NÃO aceleração "
            "estatística/causal nem previsão. Exige série econômica homogênea, "
            "calendário válido e backtest externo para qualquer uso público."
        ),
    }
