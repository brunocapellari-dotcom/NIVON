"""IVO — único caminho experimental atestado para executar benchmark ML.

Só aceita vintages sintéticas com hash por observação, duas revisões
independentes declaradas e direitos específicos. Bloqueia REAL_AUTORIZADO,
mesmo se constar em catálogos: a homologação externa precisa ser outra fase.
"""
from __future__ import annotations

from datetime import datetime

from .ivo_elegibilidade_rotulos import (
    AtestacaoResultado, avaliar_elegibilidade, serie_elegivel_experimental,
)
from .ivo_benchmark_ml import benchmark_ml_asof
from .ivo_lab_temporal import ErroLab


def executar_benchmark_sintetico_atestado(
    atestacoes:list[AtestacaoResultado], *, inicio:str, fim:str,
    corte_avaliacao:datetime, autoriza_experimento:bool=False,
    minimo_meses:int=36, backend=None,
) -> dict:
    if autoriza_experimento is not True:
        raise PermissionError("benchmark exige aprovação explícita do experimento sintético")
    if type(minimo_meses) is not int or not 36 <= minimo_meses <= 600:
        raise ErroLab("mínimo de meses inválido")
    if backend is not None and not callable(backend):
        raise ErroLab("backend inválido")
    elegibilidade=avaliar_elegibilidade(
        atestacoes,corte=corte_avaliacao,permitir_sintetico=True,
        minimo_periodos=minimo_meses)
    if elegibilidade["estado"]!="ELEGIVEL_EXPERIMENTO_SINTETICO":
        raise PermissionError("resultado final/atestações não habilitados para experimento")
    vintages=serie_elegivel_experimental(
        atestacoes,corte=corte_avaliacao,permitir_sintetico=True,
        minimo_periodos=minimo_meses)
    relatorio=benchmark_ml_asof(
        vintages,fonte=elegibilidade["fonte"],
        variavel=elegibilidade["indicador"],produto=elegibilidade["produto"],
        regiao=elegibilidade["regiao"],unidade=elegibilidade["unidade"],
        inicio=inicio,fim=fim,corte_avaliacao=corte_avaliacao,
        dados_autorizados=True,minimo_meses=minimo_meses,backend=backend,
    )
    return {
        **relatorio,
        "estado":"BENCHMARK_SINTETICO_ATTESTADO_NAO_HOMOLOGADO",
        "tipo_dados":"EXCLUSIVAMENTE_SINTETICO",
        "pacote_atestacoes_sha256":elegibilidade["hash_pacote"],
        "edicoes_vintages":len(vintages),
        "competencias_sinteticas":elegibilidade["competencias_asof"],
        "real_data_allowed":False,
        "direitos_comerciais_verificados":False,
        "modelo_homologado":False,
        "promocao_automatica":False,
        "alerta":("Somente simulação reprodutível. Não aceita dados reais nem "
                 "representa previsão de agricultura em produção."),
    }
