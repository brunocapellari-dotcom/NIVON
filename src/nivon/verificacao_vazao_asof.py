"""Auditoria de previsões de vazão: séries, vintages e métricas físicas.

Sem rede, treinamento ou declaração automática de skill em produção.
KGE segue Gupta et al. (2009); NSE segue Nash & Sutcliffe (1970).
Cada linha é uma previsão emitida para o MESMO horizonte e ponto de medição.
"""
from __future__ import annotations

from datetime import datetime, timezone
from math import fsum, isfinite, sqrt


class ErroVerificacaoVazao(ValueError):
    """Entrada incompleta, inconsistente ou temporalmente contaminada."""


def _utc(value, name):
    if not isinstance(value, str) or "T" not in value:
        raise ErroVerificacaoVazao(name + ": timestamp ISO com fuso obrigatório")
    try:
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ErroVerificacaoVazao(name + ": timestamp inválido") from exc
    if dt.tzinfo is None or dt.utcoffset() is None:
        raise ErroVerificacaoVazao(name + ": fuso obrigatório")
    return dt.astimezone(timezone.utc)


def _num(value, name, minimum=0.0, maximum=1e8):
    if type(value) not in (int, float) or not isfinite(value):
        raise ErroVerificacaoVazao(name + ": valor não finito ou booleano")
    x = float(value)
    if x < minimum or x > maximum:
        raise ErroVerificacaoVazao(name + ": fora dos limites físicos de triagem")
    return x


def _ident(value, name):
    if not isinstance(value, str) or not 3 <= len(value.strip()) <= 250:
        raise ErroVerificacaoVazao(name + ": referência obrigatória")
    return value


def _indice_kge_2009(observado, previsto):
    """KGE 2009 = 1 - sqrt((r-1)^2 + (alpha-1)^2 + (beta-1)^2).

    Sem variância observada ou prevista, r e KGE são indefinidos.
    Sem vazão observada média positiva, beta e KGE são indefinidos.
    """
    n = len(observado)
    mo = fsum(observado) / n
    mp = fsum(previsto) / n
    so2 = fsum((x - mo) ** 2 for x in observado)
    sp2 = fsum((x - mp) ** 2 for x in previsto)
    if mo <= 0 or so2 <= 0 or sp2 <= 0:
        return {"kge_2009": None, "r_pearson": None,
                "alpha_variabilidade": None, "beta_vies": None}
    r = fsum((o - mo) * (p - mp) for o, p in zip(observado, previsto))
    r = max(-1.0, min(1.0, r / sqrt(so2 * sp2)))
    alpha = sqrt(sp2 / so2)
    beta = mp / mo
    return {"kge_2009": 1.0 - sqrt((r - 1) ** 2 + (alpha - 1) ** 2 +
                                   (beta - 1) ** 2),
            "r_pearson": r, "alpha_variabilidade": alpha, "beta_vies": beta}


def avaliar_hidrograma_asof(
    *, registros, estacao_id, modelo_id, versao_modelo, referencia_vertical,
    horizonte_horas, passo_horas, fonte_observada, fonte_baseline,
    minimo=30,
):
    """Avalia vazões de um posto e horizonte com rastreabilidade temporal.

    Cada registro requer:
      estacao_id, versao_modelo, referencia_vertical, emitido_em,
      previsao_publicada_em, previsao_coletada_em, valido_em,
      features_publicadas_ate, baseline_publicado_em,
      observado_publicado_em, observado_coletado_em, observado_m3_s,
      previsto_m3_s, baseline_m3_s, qualidade, modo_validacao.

    O campo FORA_AMOSTRA é autodeclarado e NÃO prova que o treino é independente.
    Captura do prognóstico após o instante válido é barrada (não comprova
    que o prognóstico estava disponível point-in-time). Séries devem ser
    contínuas no passo informado, sem fundir postos, datums ou modelos.
    """
    for name, value in (("estação", estacao_id), ("modelo", modelo_id),
                        ("versão do modelo", versao_modelo),
                        ("referência vertical", referencia_vertical),
                        ("fonte observada", fonte_observada),
                        ("fonte baseline", fonte_baseline)):
        _ident(value, name)
    lead = _num(horizonte_horas, "horizonte em horas", 1, 720)
    step = _num(passo_horas, "passo em horas", 1 / 60, 168)
    if type(minimo) is not int or not 30 <= minimo <= 10000:
        raise ErroVerificacaoVazao("mínimo de 30 verificações")
    if not isinstance(registros, (list, tuple)) or not minimo <= len(registros) <= 50000:
        raise ErroVerificacaoVazao("série insuficiente ou extensa demais")

    observed, forecast, baseline, instants = [], [], [], []
    prev_valid = None
    effective_leads = []
    for row in registros:
        if not isinstance(row, dict):
            raise ErroVerificacaoVazao("registro não estruturado")
        if (row.get("estacao_id") != estacao_id or
            row.get("versao_modelo") != versao_modelo or
            row.get("referencia_vertical") != referencia_vertical):
            raise ErroVerificacaoVazao("estação, versão ou datum incompatível")
        if row.get("qualidade") != "APROVADO" or row.get("modo_validacao") != "FORA_AMOSTRA":
            raise ErroVerificacaoVazao("QC ou holdout declarados insuficientes")
        issue = _utc(row.get("emitido_em"), "emissão")
        published = _utc(row.get("previsao_publicada_em"), "publicação da previsão")
        captured = _utc(row.get("previsao_coletada_em"), "captura da previsão")
        valid = _utc(row.get("valido_em"), "instante válido")
        feature = _utc(row.get("features_publicadas_ate"), "última feature")
        base_pub = _utc(row.get("baseline_publicado_em"), "publicação baseline")
        obs_pub = _utc(row.get("observado_publicado_em"), "publicação observada")
        obs_capture = _utc(row.get("observado_coletado_em"), "captura observada")
        if not (feature <= issue <= published <= captured <= valid <= obs_pub <= obs_capture):
            raise ErroVerificacaoVazao("fuga temporal: emissão/vintage/publicação/coleta")
        if base_pub > published:
            raise ErroVerificacaoVazao("baseline indisponível no instante da previsão")
        if abs((valid - issue).total_seconds() / 3600 - lead) > 1e-6:
            raise ErroVerificacaoVazao("horizonte de emissão incompatível")
        if prev_valid is not None and abs((valid - prev_valid).total_seconds() / 3600 - step) > 1e-6:
            raise ErroVerificacaoVazao("lacuna, duplicata ou ordem temporal incorreta")
        prev_valid = valid
        instants.append(valid)
        effective_leads.append((valid - published).total_seconds() / 3600)
        observed.append(_num(row.get("observado_m3_s"), "observação m3/s"))
        forecast.append(_num(row.get("previsto_m3_s"), "previsão m3/s"))
        baseline.append(_num(row.get("baseline_m3_s"), "baseline m3/s"))

    n = len(observed)
    errors = [p - o for o, p in zip(observed, forecast)]
    sq = fsum(e * e for e in errors)
    baseline_sq = fsum((b - o) ** 2 for o, b in zip(observed, baseline))
    mean_obs = fsum(observed) / n
    var_obs = fsum((o - mean_obs) ** 2 for o in observed)
    seconds = step * 3600
    obs_volume = fsum(observed) * seconds
    forecast_volume = fsum(forecast) * seconds
    peak_obs = max(observed)
    peak_pred = max(forecast)
    # With tied peaks, a single "peak time" is an unjustified choice.
    if observed.count(peak_obs) == 1 and forecast.count(peak_pred) == 1:
        peak_offset = (instants[forecast.index(peak_pred)] -
                       instants[observed.index(peak_obs)]).total_seconds() / 3600
    else:
        peak_offset = None

    return {
        "estacao_id": estacao_id, "modelo_id": modelo_id,
        "versao_modelo": versao_modelo, "referencia_vertical": referencia_vertical,
        "n": n, "horizonte_emissao_horas": lead, "passo_horas": step,
        "antecedencia_efetiva_minima_horas": min(effective_leads),
        "inicio_validade_utc": instants[0].isoformat(),
        "fim_validade_utc": instants[-1].isoformat(),
        "mae_m3_s": fsum(abs(e) for e in errors) / n,
        "rmse_m3_s": sqrt(sq / n),
        "bias_m3_s": fsum(errors) / n,
        "nse": 1 - sq / var_obs if var_obs > 0 else None,
        "kge": _indice_kge_2009(observed, forecast),
        "rmse_baseline_m3_s": sqrt(baseline_sq / n),
        "skill_mse_baseline": 1 - sq / baseline_sq if baseline_sq > 0 else None,
        "volume_observado_m3": obs_volume,
        "volume_previsto_m3": forecast_volume,
        "erro_volume_m3": forecast_volume - obs_volume,
        "erro_volume_percentual": (100 * (forecast_volume / obs_volume - 1)
                                    if obs_volume > 0 else None),
        "pico_observado_m3_s": peak_obs, "pico_previsto_m3_s": peak_pred,
        "erro_horario_pico_horas": peak_offset,
        "fonte_observada": fonte_observada, "fonte_baseline": fonte_baseline,
        "natureza": "VERIFICACAO_HIDROLOGICA_ASOF_RETROSPECTIVA",
        "independencia_treino_auditada": False,
        "origem_vintages_auditada_externamente": False,
        "homologado": False,
        "limites": ("Registros, edições, veracidade das capturas, calibração e "
                    "independência temporal/espacial exigem auditoria externa. "
                    "NSE e KGE não são probabilidades; picos de série contínua "
                    "não bastam para risco de cheia nem navegabilidade."),
    }
