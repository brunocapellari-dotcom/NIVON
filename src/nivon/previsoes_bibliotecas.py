"""Previsões mensais com StatsForecast opcional; sem afirmações de precisão não medida."""
from __future__ import annotations

from datetime import date, datetime
from math import isfinite
from typing import Callable


class ErroPrevisao(ValueError):
    pass


def validar_serie_mensal(serie: list[tuple[str, float]]) -> list[tuple[str, float]]:
    if len(serie) < 24:
        raise ErroPrevisao("mínimo de 24 meses observados")
    saida = []
    meses = set()
    anterior = None
    for periodo, valor in serie:
        try:
            dt = datetime.strptime(periodo, "%Y-%m")
        except (TypeError, ValueError) as exc:
            raise ErroPrevisao("período deve ser AAAA-MM") from exc
        mes = dt.year * 12 + dt.month
        if mes in meses or (anterior is not None and mes != anterior + 1):
            raise ErroPrevisao("série deve ter meses consecutivos sem repetição")
        if isinstance(valor, bool) or not isinstance(valor, (int, float)) or not isfinite(valor) or valor < 0:
            raise ErroPrevisao("valor mensal inválido")
        meses.add(mes)
        anterior = mes
        saida.append((periodo, float(valor)))
    return saida


def _statsforecast(serie: list[tuple[str, float]], horizonte: int) -> list[float]:
    """Backend somente quando extra forecast instalado; não roda na importação."""
    try:
        import pandas as pd
        from statsforecast import StatsForecast
        from statsforecast.models import AutoETS
    except ImportError as exc:
        raise RuntimeError("Instale NIVON[forecast]") from exc
    df = pd.DataFrame([
        {"unique_id": "NIVON", "ds": pd.Timestamp(periodo + "-01"), "y": valor}
        for periodo, valor in serie
    ])
    resultado = StatsForecast(
        models=[AutoETS(season_length=12)], freq="MS", n_jobs=1
    ).forecast(df=df, h=horizonte)
    if "AutoETS" not in resultado.columns:
        raise ErroPrevisao("saída de StatsForecast sem coluna AutoETS")
    return [float(x) for x in resultado["AutoETS"].tolist()]


def prever_mensal(
    serie: list[tuple[str, float]], *,
    horizonte: int = 3, backend: Callable | None = None,
) -> dict:
    dados = validar_serie_mensal(serie)
    if not isinstance(horizonte, int) or not 1 <= horizonte <= 12:
        raise ErroPrevisao("horizonte precisa estar entre 1 e 12 meses")
    executor = backend or _statsforecast
    valores = executor(dados, horizonte)
    if len(valores) != horizonte or any(not isfinite(float(v)) or float(v) < 0 for v in valores):
        raise ErroPrevisao("previsões inválidas")
    ultimo = datetime.strptime(dados[-1][0], "%Y-%m")
    saida = []
    for i, v in enumerate(valores, 1):
        k = ultimo.year * 12 + ultimo.month - 1 + i
        periodo = "%04d-%02d" % (k // 12, k % 12 + 1)
        saida.append({"periodo": periodo, "estimativa": float(v)})
    return {
        "modelo": "STATSFORECAST_AUTOETS",
        "estado": "CENARIO_NAO_HOMOLOGADO",
        "base_ate": dados[-1][0],
        "previsoes": saida,
        "aviso": "Requer vintage as-of, dados reais e backtest independente antes de publicação preditiva.",
    }


def backtest_mensal(
    serie: list[tuple[str, float]], *,
    folds: int = 3, backend: Callable | None = None
) -> dict:
    """Walk-forward de um mês sem fuga temporal; benchmark sazonal t-12."""
    dados = validar_serie_mensal(serie)
    if folds < 3 or len(dados) - folds < 24:
        raise ErroPrevisao("histórico insuficiente para backtest temporal")
    executor = backend or _statsforecast
    resultados = []
    for i in range(len(dados) - folds, len(dados)):
        treino = dados[:i]
        real = dados[i][1]
        previsto = executor(treino, 1)
        if len(previsto) != 1 or not isfinite(float(previsto[0])) or float(previsto[0]) < 0:
            raise ErroPrevisao("previsão inválida no fold")
        base = dados[i - 12][1]
        resultados.append({
            "periodo": dados[i][0], "observado": real,
            "previsao": float(previsto[0]), "baseline_sazonal": base,
            "erro_modelo": abs(real - float(previsto[0])),
            "erro_baseline": abs(real - base),
        })
    mae = sum(x["erro_modelo"] for x in resultados) / folds
    mae_base = sum(x["erro_baseline"] for x in resultados) / folds
    return {
        "folds": resultados, "mae_modelo": mae, "mae_baseline": mae_base,
        "superou_baseline": mae < mae_base,
        "status": "BACKTEST_EXECUTADO_VALIDACAO_REAL_ASOF_PENDENTE",
        "publicar_como_previsao_validada": False,
    }
