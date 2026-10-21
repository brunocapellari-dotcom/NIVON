"""Adaptador de relatório quantitativo da PR #21; NÃO recalcula forecasts.

O Brier multiclasse de Mercados usa soma das perdas de três categorias.
quant_core reporta soma/3. ECE de confiança máxima não equivale aos
reliability bins one-vs-rest. Nenhuma conversão homologa probabilidades.
"""
from __future__ import annotations
from math import isfinite
from typing import Mapping
from .quant_core import ErroQuantitativo, _identidade


def _num(v: object, nome: str, *, minimo: float = 0, maximo: float | None = None) -> float:
    if type(v) not in (float, int) or not isfinite(v):
        raise ErroQuantitativo(f"{nome}: numero finito obrigatorio")
    f=float(v)
    if f < minimo or (maximo is not None and f > maximo):
        raise ErroQuantitativo(f"{nome}: fora dos limites")
    return f


def normalizar_relatorio_brier_mercados(relatorio: Mapping) -> dict:
    """Tradução tipada de score prequential *agregado* de Mercados para Quant.

    Não toma decisão de publicar, não reconstrói observações nem retreina.
    Exige relatório detalhado suficiente para comprovar a aritmética do score.
    Não assume que dados, vintages ou calendário foram auditados externamente.
    """
    if not isinstance(relatorio, Mapping):
        raise ErroQuantitativo("relatorio de Mercados precisa ser objeto")
    if relatorio.get("status") != "BACKTEST_TEMPORAL_OFFLINE_NAO_HOMOLOGADO":
        raise ErroQuantitativo("relatorio sem backtest temporal avaliavel")
    if relatorio.get("publicavel") is not False or relatorio.get("probabilidades_calibradas", "MISSING") is not None:
        raise ErroQuantitativo("gates de publicação/calibração incompatíveis")
    for k in ("serie_id", "modelo_versao", "regra_rotulagem"):
        _identidade(relatorio.get(k), k)
    h = relatorio.get("horizonte_sessoes")
    n = relatorio.get("avaliacoes")
    total = relatorio.get("amostra_total")
    if any(type(v) is not int for v in (h,n,total)) or not (1 <= h <= 365 and 30 <= n <= total <= 200000):
        raise ErroQuantitativo("amostra/horizonte de Mercado invalidos")
    raw=_num(relatorio.get("brier_multiclasse"),"brier_mercados_soma",maximo=2)
    raw_baseline=_num(relatorio.get("brier_benchmark_expansivo"),"brier_baseline_soma",maximo=2)
    ece=_num(relatorio.get("ece_confianca"),"ece_top_class",maximo=1)
    logloss=_num(relatorio.get("logloss_media"),"logloss_media")
    reported_skill=relatorio.get("skill_brier_vs_benchmark")
    skill = None if raw_baseline == 0 else 1 - raw/raw_baseline
    if skill is None:
        if reported_skill is not None:
            raise ErroQuantitativo("skill indefinida quando benchmark tem Brier zero")
    else:
        if type(reported_skill) not in (float,int) or not isfinite(reported_skill) or abs(reported_skill-skill)>1e-9:
            raise ErroQuantitativo("skill do benchmark inconsistente")
    bins=relatorio.get("bins_calibracao")
    if not isinstance(bins,list) or not bins:
        raise ErroQuantitativo("faltam bins de confianca")
    qtd=0
    for x in bins:
        if not isinstance(x,Mapping) or type(x.get("n")) is not int or x["n"] < 1:
            raise ErroQuantitativo("bin de confianca invalido")
        conf=_num(x.get("confianca_media"),"confianca",maximo=1)
        acerto=_num(x.get("acerto"),"acerto",maximo=1)
        faixa=x.get("faixa")
        if not isinstance(faixa,list) or len(faixa)!=2:
            raise ErroQuantitativo("faixa do bin ausente")
        a=_num(faixa[0],"limite_inferior",maximo=1)
        b=_num(faixa[1],"limite_superior",maximo=1)
        if not a < b or not a-1e-9 <= conf <= b+1e-9:
            raise ErroQuantitativo("bin fora do dominio")
        qtd+=x["n"]
    if qtd != n:
        raise ErroQuantitativo("bins nao cobrem todas as avaliacoes")
    return {
        "status":"RELATORIO_MERCADOS_NORMALIZADO_NAO_HOMOLOGADO",
        "serie_id":relatorio["serie_id"],"modelo_versao":relatorio["modelo_versao"],
        "regra_rotulagem":relatorio["regra_rotulagem"],
        "horizonte_periodos":h,"periodos_tipo":"SESSOES",
        "n_folds":n,"brier_soma_tres_classes":raw,
        "brier_multiclasse_medio":raw/3,
        "brier_benchmark_expansivo_medio":raw_baseline/3,
        "skill_brier_vs_benchmark":skill,
        "ece_confianca_maxima":ece,"logloss_media":logloss,
        "convencao_brier":"SOMA_ERROS_QUADRATICOS_DIVIDIDA_POR_3",
        "calibracao_verificada":False,"probabilidades_calibradas":None,
        "publicavel":False,
        "limite":"Conversao de scores agregados; sem prova independente de labels, vintages, calendario ou treino."
    }
