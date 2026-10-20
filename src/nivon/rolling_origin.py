"""Validação rolling-origin estrita, offline, com dados vintage-as-of.

A função do modelo recebe APENAS os dados disponíveis na emissão e contexto
sem rótulo futuro. Não busca dados, não calibra probabilidades, não publica.
Metadados/forecasts fornecidos exigem comprovação independente de origem.
"""
from __future__ import annotations

from datetime import datetime
from math import isfinite
from types import MappingProxyType
from typing import Callable, Mapping, Sequence

from .quant_core import (
    ErroQuantitativo, _identidade, _instante, _numero,
    avaliar_previsoes_oos, preparar_folds_asof,
)

SAIDAS_OPCIONAIS = frozenset({
    "probabilidades", "intervalo_inferior", "intervalo_superior",
    "nivel_intervalo",
})


def _resultado_modelo(resultado: object, *, nao_negativo: bool) -> dict:
    """Retém somente estimativas; rejeita rótulos, metadados e saídas ocultas."""
    if isinstance(resultado, Mapping):
        if set(resultado) - (SAIDAS_OPCIONAIS | {"previsto"}):
            raise ErroQuantitativo("modelo retornou campo nao autorizado")
        if "previsto" not in resultado:
            raise ErroQuantitativo("modelo sem previsto")
        extras = {key: value for key, value in resultado.items() if key != "previsto"}
        if ("probabilidades" in extras and
                not isinstance(extras["probabilidades"], Mapping)):
            raise ErroQuantitativo("probabilidades devem ser mapeamento")
    else:
        extras = {}
        resultado = {"previsto": resultado}
    preco = _numero(resultado["previsto"], "previsto", nao_negativo=nao_negativo)
    return {"previsto": preco, **extras}


def executar_rolling_origin_asof(
    observacoes: Sequence[Mapping], *, calendario: Sequence[str],
    origens_em: Mapping[str, str], as_of_avaliacao: str,
    serie_id: str, unidade: str, fonte_id: str, modelo_id: str,
    horizonte_periodos: int, tamanho_treino: int,
    modelo: Callable[[tuple[Mapping, ...], Mapping], object],
    min_folds: int = 5, nao_negativo: bool = True,
    tolerancia_absoluta: float = 0.0,
    tolerancia_relativa: float = 0.0,
) -> dict:
    """Reexecuta previsão point-in-time; usa persistência como baseline.

    Cada origem recebe apenas (treino imutável, metadados imutáveis). O alvo
    real é inserido NO ARQUIVO DE AVALIAÇÃO depois que o modelo retorna.
    Origem-alvo segue calendário explícito (sessões ou competências), jamais
    dias corridos implícitos. Treino é janela móvel de tamanho_treino.

    Esta rotina não consegue provar que a implementação de 'modelo' não
    utiliza variáveis globais externas; auditoria de código e isolamento de
    execução ainda são necessários.
    """
    for nome, valor in (("serie_id", serie_id), ("unidade", unidade),
                        ("fonte_id", fonte_id), ("modelo_id", modelo_id)):
        _identidade(valor, nome)
    if not callable(modelo):
        raise ErroQuantitativo("modelo precisa ser função callable")
    if type(min_folds) is not int or min_folds < 5:
        raise ErroQuantitativo("ao menos 5 origens para auditoria")
    if not isinstance(origens_em, Mapping) or not min_folds <= len(origens_em) <= 2000:
        raise ErroQuantitativo("quantidade de origens insuficiente/excessiva")
    folds = preparar_folds_asof(
        observacoes, calendario=calendario,
        origens_em=origens_em, as_of_avaliacao=as_of_avaliacao,
        serie_id=serie_id, unidade=unidade, fonte_id=fonte_id,
        horizonte_periodos=horizonte_periodos, minimo_treino=tamanho_treino,
    )
    registros = []
    for fold in folds:
        bruto = fold["treino_asof"]
        if len(bruto) != tamanho_treino:
            raise ErroQuantitativo("tamanho de treinamento inconsistente")
        # Cópias independentes, só leitura e sem qualquer rótulo de avaliação.
        treino = tuple(MappingProxyType({
            "periodo": row["periodo"], "valor": row["valor"],
            "disponivel_em": row["disponivel_em"],
            "publicado_em": row["publicado_em"],
            "edicao_sha256": row["edicao_sha256"],
        }) for row in bruto)
        contexto = MappingProxyType({
            "serie_id": serie_id, "unidade": unidade,
            "modelo_id": modelo_id,
            "periodo_origem": fold["periodo_origem"],
            "alvo_periodo": fold["alvo_periodo"],
            "emitido_em": fold["emitido_em"],
            "horizonte_periodos": horizonte_periodos,
        })
        saida = _resultado_modelo(modelo(treino, contexto),
                                 nao_negativo=nao_negativo)
        disponibilidade = max(_instante(r["disponivel_em"], "disponivel_em")
                              for r in bruto).isoformat()
        # Baseline de persistência usa o último valor realmente conhecido
        # segundo o calendario, nunca o resultado realizado no alvo.
        baseline = bruto[-1]["valor"]
        base = _numero(baseline, "baseline", nao_negativo=nao_negativo)
        real = _numero(fold["real_avaliacao"], "real",
                       nao_negativo=nao_negativo)
        registro = {
            "serie_id": serie_id, "modelo_id": modelo_id,
            "unidade": unidade, "baseline_id": "PERSISTENCIA_ASOF",
            "horizonte_periodos": horizonte_periodos,
            "periodo_origem": fold["periodo_origem"],
            "alvo_periodo": fold["alvo_periodo"],
            "emitido_em": fold["emitido_em"],
            "dados_disponiveis_ate": disponibilidade,
            "treino_disponivel_ate": disponibilidade,
            "observado_publicado_em": fold["real_publicado_em"],
            "observado_coletado_em": fold["real_coletado_em"],
            "edicao_sha256": fold["real_edicao_sha256"],
            "valor_base": base, "baseline": base, "real": real,
            **saida,
        }
        registros.append(registro)
    # A função auditora é o único lugar que produz métricas. Falhas de
    # contratos probabilísticos e intervalos interrompem toda a avaliação.
    metricas = avaliar_previsoes_oos(
        registros, calendario=calendario, serie_id=serie_id,
        modelo_id=modelo_id, unidade=unidade, baseline_id="PERSISTENCIA_ASOF",
        horizonte_periodos=horizonte_periodos, as_of_avaliacao=as_of_avaliacao,
        min_folds=min_folds, nao_negativo=nao_negativo,
        tolerancia_absoluta=tolerancia_absoluta,
        tolerancia_relativa=tolerancia_relativa,
    )
    return {
        "status": "ROLLING_ORIGIN_SINTETICO_OU_RETROSPECTIVO_NAO_HOMOLOGADO",
        "serie_id": serie_id, "modelo_id": modelo_id, "fonte_id": fonte_id,
        "unidade": unidade, "horizonte_periodos": horizonte_periodos,
        "tamanho_treino": tamanho_treino, "n_folds": len(registros),
        "benchmark": "PERSISTENCIA_ASOF", "metricas": metricas,
        "arquivo_avaliacao": registros, "publicavel": False,
        "prova_integridade_externa_pendente": True,
        "alerta": "O preditor pode acessar fontes externas/globais; isolar runtime,"
                  " verificar logs imutaveis e vintage real antes de chamar OOS"
                  " genuino ou promover previsao.",
    }
