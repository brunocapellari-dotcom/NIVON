"""Avaliação temporal determinística de previsões anuais de demanda.

CAGR só pode ser tratado como cenário até demonstrar valor fora da amostra.
A entrada deve ser previamente selecionada em modo AS-OF com data de corte.
"""
from __future__ import annotations

from math import isfinite
from typing import Mapping


class ErroValidacao(ValueError):
    pass


def avaliar_crescimento_anual(
    serie: Mapping[int, float], *, janela: int = 3, minimo_testes: int = 3
) -> dict:
    """Walk-forward um passo: CAGR vs último valor, sem usar o ano previsto no treino.

    Proíbe chamar os resultados de previsão validada: testes com séries reais,
    vintages as-of e relevância estatística são gates separados.
    """
    if janela not in (3, 4, 5) or minimo_testes < 3:
        raise ErroValidacao("janela 3–5 anos, mínimo de 3 folds")
    if not serie:
        raise ErroValidacao("série vazia")
    anos = sorted(serie)
    if anos != list(range(anos[0], anos[-1] + 1)):
        raise ErroValidacao("anos não consecutivos")
    for ano, valor in serie.items():
        if isinstance(valor, bool) or not isinstance(valor, (float, int)) or not isfinite(valor) or valor <= 0:
            raise ErroValidacao(f"valor anual inválido em {ano}")
    if len(anos) < janela + minimo_testes + 1:
        raise ErroValidacao("histórico insuficiente para validação temporal")
    folds = []
    for i in range(janela, len(anos) - 1):
        t = anos[i]
        anterior = float(serie[t])
        passado = float(serie[anos[i - janela]])
        real = float(serie[anos[i + 1]])
        cagr = (anterior / passado) ** (1.0 / janela) - 1.0
        previsao_cagr = anterior * (1.0 + cagr)
        previsao_baseline = anterior
        folds.append({
            "ano_treino_ate": t,
            "ano_previsto": anos[i + 1],
            "observado": real,
            "previsto_cagr": previsao_cagr,
            "previsto_baseline_ultimo_valor": previsao_baseline,
            "erro_absoluto_cagr": abs(previsao_cagr - real),
            "erro_absoluto_baseline": abs(previsao_baseline - real),
        })
    if len(folds) < minimo_testes:
        raise ErroValidacao("folds insuficientes")
    soma_real = sum(f["observado"] for f in folds)
    erro_cagr = sum(f["erro_absoluto_cagr"] for f in folds)
    erro_base = sum(f["erro_absoluto_baseline"] for f in folds)
    return {
        "status": "BACKTEST_SINTETICO_OU_HISTORICO_NAO_HOMOLOGADO",
        "horizonte": "1 ANO A FRENTE",
        "metodo": f"CAGR_{janela}_ANOS",
        "referencia": "ULTIMO_VALOR",
        "folds": folds,
        "quantidade_folds": len(folds),
        "mae_cagr": erro_cagr / len(folds),
        "mae_baseline": erro_base / len(folds),
        "wape_cagr": erro_cagr / soma_real,
        "wape_baseline": erro_base / soma_real,
        "melhora_sobre_baseline": erro_cagr < erro_base,
        "pode_promover_modelo": False,
        "motivo_gate": "faltam vintages as-of, fonte real e validação estatística",
    }
