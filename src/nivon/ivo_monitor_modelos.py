"""IVO: detector offline de degradação do erro preditivo.

Monitora desempenho de um mesmo modelo, local, unidade e horizonte. Não é
detector causal de data drift nem gatilho de treinamento ou publicação.
"""
from __future__ import annotations

from math import isfinite

from .ivo_previsao_ledger import ErroLedger


def diagnosticar_performance(avaliacao: dict, *, minimo_historico: int = 6,
                            janela_recente: int = 3, fator_alerta: float = 1.5,
                            cobertura_minima: float = 0.7) -> dict:
    if not isinstance(avaliacao, dict) or avaliacao.get("status") != "AVALIACAO_DESCRITIVA_NAO_HOMOLOGADA":
        raise ErroLedger("necessária avaliação comparável do ledger")
    if type(minimo_historico) is not int or minimo_historico < 3:
        raise ErroLedger("mínimo histórico inválido")
    if type(janela_recente) is not int or janela_recente < 2:
        raise ErroLedger("janela recente inválida")
    if (type(fator_alerta) not in (float, int) or not isfinite(fator_alerta)
            or fator_alerta <= 1):
        raise ErroLedger("limiar de alerta inválido")
    if (type(cobertura_minima) not in (float, int) or not isfinite(cobertura_minima)
            or not 0 < cobertura_minima < 1):
        raise ErroLedger("limiar de cobertura inválido")
    pontos = sorted(avaliacao.get("avaliacoes", []), key=lambda x: x["periodo"])
    periodos = [x["periodo"] for x in pontos]
    if len(periodos) != len(set(periodos)):
        raise ErroLedger("avaliações múltiplas do mesmo período não são comparáveis para drift")
    if len(pontos) < minimo_historico + janela_recente:
        return {
            "status": "HISTORICO_INSUFICIENTE",
            "amostras": len(pontos),
            "necessarias": minimo_historico + janela_recente,
            "sugere_reavaliacao": False,
            "retreino_automatico": False,
            "promocao_automatica": False,
        }
    base = pontos[:-janela_recente]
    recentes = pontos[-janela_recente:]
    def media_erro(itens):
        return sum(x["erro_absoluto"] for x in itens)/len(itens)
    mae_anterior = media_erro(base)
    mae_recente = media_erro(recentes)
    fator = mae_recente/mae_anterior if mae_anterior else (float("inf") if mae_recente else 1.)
    # Limite com baseline: erro subiu em relação à história E não está
    # melhorando contra a referência ingênua na janela recente.
    base_recente = sum(x["erro_baseline"] for x in recentes)/len(recentes)
    erro_alto = fator >= fator_alerta and mae_recente > mae_anterior
    intervalos = [x["dentro_intervalo"] for x in recentes if x["dentro_intervalo"] is not None]
    cobertura = sum(intervalos)/len(intervalos) if intervalos else None
    cobertura_ruim = cobertura is not None and cobertura < cobertura_minima
    alerta = erro_alto or cobertura_ruim
    return {
        "status": "ALERTA_DESEMPENHO" if alerta else "SEM_ALERTA_NESTA_JANELA",
        "modo": avaliacao["modo"], "verdade": avaliacao["verdade"],
        "mae_historico": mae_anterior, "mae_recente": mae_recente,
        "mae_baseline_recente": base_recente,
        "fator_erro_recente": fator if isfinite(fator) else None,
        "historico_erro_zero_e_novo_erro": mae_anterior == 0 and mae_recente > 0,
        "aumento_erro": erro_alto, "cobertura_recente": cobertura,
        "cobertura_baixa": cobertura_ruim,
        "total_historico": len(base), "total_recente": len(recentes),
        "sugere_reavaliacao": alerta,
        "retreino_automatico": False, "promocao_automatica": False,
        "limitacao": ("Alteração de erro não demonstra mudança causal no ambiente "
                     "nem justifica trocar automaticamente um modelo. Requer dados "
                     "reais autorizados, avaliação independente e validação temporal."),
    }
