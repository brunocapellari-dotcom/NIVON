"""Auditoria conservadora do holdout rolling-origin point-in-time.

Usa somente forecasts arquivados e auditados pelo quant_core; NUNCA
retreina, não calcula p-values iid nem publica previsão. Rotula explicitamente
a sobreposição de horizontes e limita a evidência ao contrato declarado.
"""
from __future__ import annotations

from collections import defaultdict
from math import fsum, isfinite, sqrt
from typing import Mapping, Sequence

from .quant_core import (
    ErroQuantitativo, _calendario, _dia, _instante,
    avaliar_previsoes_oos,
)


def _inteiro(v: object, nome: str, menor: int, maior: int) -> int:
    if type(v) is not int or not menor <= v <= maior:
        raise ErroQuantitativo(f"{nome}: inteiro fora do dominio")
    return v


def _desempenho(folds: Sequence[Mapping]) -> dict:
    if not folds:
        raise ErroQuantitativo("desempenho com folds vazios")
    n = len(folds)
    abs_e = [abs(r["erro_modelo"]) for r in folds]
    abs_b = [abs(r["erro_baseline"]) for r in folds]
    sum_e2 = fsum(r["erro_modelo"] ** 2 for r in folds)
    sum_b2 = fsum(r["erro_baseline"] ** 2 for r in folds)
    mae = fsum(abs_e) / n
    base = fsum(abs_b) / n
    rmse = sqrt(sum_e2 / n)
    base_rmse = sqrt(sum_b2 / n)
    if not all(isfinite(v) for v in (mae, base, rmse, base_rmse)):
        raise ErroQuantitativo("metricas holdout com overflow")
    return {
        "n": n, "mae": mae, "rmse": rmse,
        "mae_baseline": base, "rmse_baseline": base_rmse,
        "ganho_mae_baseline": None if base == 0 else 1 - mae / base,
        "ganho_rmse_baseline": None if base_rmse == 0 else 1 - rmse / base_rmse,
    }


def avaliar_holdout_temporal_purgado(
    registros: Sequence[Mapping], *, calendario: Sequence[str],
    serie_id: str, modelo_id: str, unidade: str, baseline_id: str,
    horizonte_periodos: int, as_of_avaliacao: str,
    n_holdout: int = 30, minimo_historico_elegivel: int = 30,
    minimo_por_fase_disjunta: int = 5, embargo_periodos: int = 1,
    nao_negativo: bool = True,
) -> dict:
    """Avalia holdout retrospectivo com purga temporal e fases disjuntas.

    O histórico elegível é composto só por previsões cujo resultado foi
    coletado ANTES da primeira emissão holdout e cujo alvo está pelo menos
    embargo_periodos antes da primeira origem holdout. NÃO se usa holdout
    para treinar/calibrar; os metadados de treino declarados exigem prova real.

    Para horizonte H, origens de mesmo índice mod H têm alvos não
    sobrepostos no calendário declarado. Cada fase possui sua métrica;
    superioridade requer ganhos positivos de MAE e RMSE em TODAS as fases
    suficientemente amostradas. Mesmo assim o sinal é NÃO HOMOLOGADO.
    """
    nh = _inteiro(n_holdout, "n_holdout", 10, 20000)
    mh = _inteiro(minimo_historico_elegivel, "minimo_historico_elegivel", 10, 20000)
    mf = _inteiro(minimo_por_fase_disjunta, "minimo_por_fase_disjunta", 5, 20000)
    embargo = _inteiro(embargo_periodos, "embargo_periodos", 1, 365)
    if nh < mf:
        raise ErroQuantitativo("holdout deve comportar a amostra minima por fase")
    dias, mapa = _calendario(calendario)
    corte = _instante(as_of_avaliacao, "as_of_avaliacao")
    # Reutilizar o contrato único: horários de emissão/treino/features,
    # série/horizonte/identidade, maturação de alvos, hashes e duplicatas.
    auditoria = avaliar_previsoes_oos(
        registros, calendario=calendario, serie_id=serie_id,
        modelo_id=modelo_id, unidade=unidade, baseline_id=baseline_id,
        horizonte_periodos=horizonte_periodos,
        as_of_avaliacao=as_of_avaliacao,
        min_folds=5, nao_negativo=nao_negativo,
    )
    pares = [
        (r, row) for r, row in zip(registros, auditoria["folds"])
    ]
    pares.sort(key=lambda par: mapa[_dia(par[0]["periodo_origem"], "periodo_origem")])
    # Rejeitar backfills em que emissões não seguem as origens crescentes:
    # a assinatura histórica dessas emissões deve ser verificada externamente.
    if any(
        _instante(a[0]["emitido_em"], "emitido_em") >=
        _instante(b[0]["emitido_em"], "emitido_em")
        for a, b in zip(pares, pares[1:])
    ):
        raise ErroQuantitativo("emissoes fora da ordem temporal das origens")
    if len(pares) < nh + mh:
        return {
            "status": "AMOSTRA_HOLDOUT_INSUFICIENTE",
            "n_total": len(pares), "n_holdout_solicitado": nh,
            "minimo_historico_elegivel": mh, "publicavel": False,
            "habilitado_para_producao": False,
        }
    passado, futuro = pares[:-nh], pares[-nh:]
    emissao_inicio = _instante(futuro[0][0]["emitido_em"], "emitido_em")
    primeira_origem = mapa[_dia(futuro[0][0]["periodo_origem"], "periodo_origem")]
    historico_elegivel = [
        (r, row) for r, row in passado
        if (_instante(r["observado_coletado_em"], "observado_coletado_em")
            < emissao_inicio and
            primeira_origem - mapa[_dia(r["alvo_periodo"], "alvo_periodo")]
            >= embargo)
    ]
    excluidos = len(passado) - len(historico_elegivel)
    if len(historico_elegivel) < mh:
        return {
            "status": "HISTORICO_PURGADO_INSUFICIENTE",
            "n_total": len(pares), "n_holdout": len(futuro),
            "n_historico_elegivel": len(historico_elegivel),
            "n_excluidos_pela_purga": excluidos,
            "primeira_emissao_holdout": emissao_inicio.isoformat(),
            "publicavel": False, "habilitado_para_producao": False,
        }
    fases = defaultdict(list)
    for r, fold in futuro:
        index = mapa[_dia(r["periodo_origem"], "periodo_origem")]
        fases[index % horizonte_periodos].append(fold)
    resultado_fases = [
        {"fase": k, **_desempenho(v)} for k, v in sorted(fases.items())
    ]
    todos_disjuntos = all(x["n"] >= mf for x in resultado_fases)
    conjunto_holdout = [f for _, f in futuro]
    geral = _desempenho(conjunto_holdout)
    positivos = all(
        x["ganho_mae_baseline"] is not None
        and x["ganho_rmse_baseline"] is not None
        and x["ganho_mae_baseline"] > 0
        and x["ganho_rmse_baseline"] > 0
        for x in resultado_fases
    )
    if not todos_disjuntos:
        status = "FASES_DISJUNTAS_INSUFICIENTES"
    elif positivos:
        status = "SINAL_DESCRITIVO_HOLDOUT_NAO_HOMOLOGADO"
    else:
        status = "SEM_SUPERIORIDADE_ROBUSTA_AO_BASELINE"
    return {
        "status": status,
        "serie_id": serie_id, "modelo_id": modelo_id, "unidade": unidade,
        "baseline_id": baseline_id, "horizonte_periodos": horizonte_periodos,
        "as_of_avaliacao": corte.isoformat(),
        "primeira_emissao_holdout": emissao_inicio.isoformat(),
        "n_total": len(pares), "n_holdout": nh,
        "n_historico_elegivel": len(historico_elegivel),
        "n_excluidos_pela_purga": excluidos,
        "embargo_periodos": embargo,
        "metricas_holdout": geral,
        "metricas_fases_nao_sobrepostas": resultado_fases,
        "quantidade_fases": len(resultado_fases),
        "minimo_por_fase": mf, "fases_suficientes": todos_disjuntos,
        "superioridade_em_todas_as_fases": bool(todos_disjuntos and positivos),
        "percentis_ou_significancia_iid": None,
        "calibracao_probabilistica_verificada": False,
        "historico_externo_provado": False,
        "publicavel": False, "habilitado_para_producao": False,
        "aviso": "Evidencia descritiva de arquivos declarados. "
                 "Fases de alvos nao sobrepostos nao garantem independencia "
                 "estatistica; regimes, selecao de hiperparametros, vintages, "
                 "calendario e holdout intocado exigem auditoria independente.",
    }
