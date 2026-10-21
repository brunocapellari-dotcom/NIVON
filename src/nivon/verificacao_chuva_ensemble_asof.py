"""Verificação ex ante de precipitação ACUMULADA por intervalo, sem rede.

Uma medição de chuva é a integral de um intervalo, não um valor pontual
no instante de validade. Só compara observações e ensembles de mesma
estação, janela, produto, versão e antecedência de emissão. Não atesta
qualidade das fontes, independência do treinamento ou calibração real.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from math import fsum, isfinite, sqrt
from .meteorologia_probabilistica import crps_ensemble


class ErroVerificacaoChuva(ValueError):
    pass


def _tempo(value, label):
    if not isinstance(value, str) or "T" not in value:
        raise ErroVerificacaoChuva(label + ": data/hora ISO com fuso obrigatória")
    try:
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ErroVerificacaoChuva(label + ": data/hora inválida") from exc
    if dt.tzinfo is None or dt.utcoffset() is None:
        raise ErroVerificacaoChuva(label + ": fuso obrigatório")
    return dt.astimezone(timezone.utc)


def _numero(x, label, minimum=0, maximum=5000):
    if type(x) not in (int, float) or not isfinite(x):
        raise ErroVerificacaoChuva(label + ": valor não finito ou não numérico")
    v = float(x)
    if v < minimum or v > maximum:
        raise ErroVerificacaoChuva(label + ": fora do domínio de triagem")
    return v


def _ident(x, label):
    if not isinstance(x, str) or not 3 <= len(x.strip()) <= 250:
        raise ErroVerificacaoChuva(label + ": identificador/proveniência obrigatório")
    return x


def verificar_chuva_ensemble_asof(
    *, registros, estacao_id, produto_id, versao_produto,
    limiar_evento_mm, horizonte_horas, acumulacao_horas,
    passo_horas, fonte_observacao, fonte_climatologia, minimo=30,
):
    """Verifica até 100 membros NWP e 20000 períodos NÃO SOBREPOSTOS.

    Cada registro: estacao_id, produto_id, versao_produto,
    suporte_temporal='ACUMULADO_INTERVALO', emitido_em,
    previsao_publicada_em, previsao_coletada_em,
    features_publicadas_ate, valido_em (fim da janela de acumulação),
    obs_publicado_em, obs_coletado_em, climatologia_publicada_em,
    observado_mm, membros_mm, prob_climatologica, qc, modo_validacao.

    A previsão e a climatologia DEVEM estar disponíveis antes do INÍCIO
    de cada janela, não somente antes da validade final. Horários fornecidos
    não substituem um ledger externo de snapshots point-in-time.
    """
    for label, obj in (("estação", estacao_id), ("produto", produto_id),
                       ("versão", versao_produto), ("observação", fonte_observacao),
                       ("climatologia", fonte_climatologia)):
        _ident(obj, label)
    threshold = _numero(limiar_evento_mm, "limiar do evento")
    lead = _numero(horizonte_horas, "horizonte", 1, 720)
    window = _numero(acumulacao_horas, "acumulação", 1 / 60, 720)
    step = _numero(passo_horas, "passo", 1 / 60, 720)
    if lead < window or step < window:
        raise ErroVerificacaoChuva("previsão deve preceder toda a janela; séries não podem sobrepor períodos")
    if type(minimo) is not int or not 30 <= minimo <= 20000:
        raise ErroVerificacaoChuva("mínimo de 30 verificações obrigatórias")
    if not isinstance(registros, (list, tuple)) or not minimo <= len(registros) <= 20000:
        raise ErroVerificacaoChuva("série insuficiente ou excessivamente longa")

    member_n = None
    previous_valid = None
    observations = []
    forecasts = []
    probabilities = []
    baselines = []
    bs_sum = 0.0
    bs_ref_sum = 0.0
    crps_sum = 0.0
    absolute = 0.0
    sq_error = 0.0
    signed_error = 0.0
    event_count = 0
    bins = [{"n": 0, "prob_total": 0.0, "eventos": 0} for _ in range(10)]
    effective_lead = []

    for row in registros:
        if not isinstance(row, dict):
            raise ErroVerificacaoChuva("registro não estruturado")
        if (row.get("estacao_id") != estacao_id or
            row.get("produto_id") != produto_id or
            row.get("versao_produto") != versao_produto or
            row.get("suporte_temporal") != "ACUMULADO_INTERVALO"):
            raise ErroVerificacaoChuva("identidade, versão ou suporte temporal incompatível")
        if row.get("qc") != "APROVADO" or row.get("modo_validacao") != "FORA_AMOSTRA":
            raise ErroVerificacaoChuva("QC ou holdout declarados insuficientes")
        issue = _tempo(row.get("emitido_em"), "emissão")
        published = _tempo(row.get("previsao_publicada_em"), "publicação previsão")
        captured = _tempo(row.get("previsao_coletada_em"), "captura previsão")
        features = _tempo(row.get("features_publicadas_ate"), "features")
        valid = _tempo(row.get("valido_em"), "fim do intervalo")
        obs_pub = _tempo(row.get("obs_publicado_em"), "publicação observação")
        obs_col = _tempo(row.get("obs_coletado_em"), "captura observação")
        clim_pub = _tempo(row.get("climatologia_publicada_em"), "publicação climatologia")
        start = valid - timedelta(hours=window)
        if not (features <= issue <= published <= captured <= start <= valid <= obs_pub <= obs_col):
            raise ErroVerificacaoChuva("fuga temporal, ausência de vintage ou previsão intraintervalo")
        if clim_pub > issue:
            raise ErroVerificacaoChuva("climatologia indisponível na emissão da previsão")
        if abs((valid - issue).total_seconds() / 3600 - lead) > 1e-6:
            raise ErroVerificacaoChuva("mistura de horizontes de emissão")
        if previous_valid is not None and abs((valid - previous_valid).total_seconds() / 3600 - step) > 1e-6:
            raise ErroVerificacaoChuva("datas duplicadas, desordenadas ou lacuna no passo")
        previous_valid = valid
        effective_lead.append((start - captured).total_seconds() / 3600)

        observed = _numero(row.get("observado_mm"), "chuva observada")
        members = row.get("membros_mm")
        if not isinstance(members, (list, tuple)) or not 3 <= len(members) <= 100:
            raise ErroVerificacaoChuva("ensemble requer 3 a 100 membros")
        if member_n is None:
            member_n = len(members)
        if len(members) != member_n:
            raise ErroVerificacaoChuva("membro de ensemble ausente")
        members = [_numero(x, "chuva prevista") for x in members]
        climatology = _numero(row.get("prob_climatologica"), "probabilidade base", 0, 1)

        event = int(observed >= threshold)
        probability = sum(x >= threshold for x in members) / member_n
        prediction = fsum(members) / member_n
        error = prediction - observed
        bs_sum += (probability - event) ** 2
        bs_ref_sum += (climatology - event) ** 2
        crps_sum += crps_ensemble(observed, members)
        absolute += abs(error)
        sq_error += error ** 2
        signed_error += error
        event_count += event
        bin_index = min(9, int(probability * 10))
        bins[bin_index]["n"] += 1
        bins[bin_index]["prob_total"] += probability
        bins[bin_index]["eventos"] += event
        observations.append(observed)
        forecasts.append(prediction)
        probabilities.append(probability)
        baselines.append(climatology)

    n = len(registros)
    ref_brier = bs_ref_sum / n
    return {
        "estacao_id": estacao_id, "produto_id": produto_id,
        "versao_produto": versao_produto,
        "natureza": "VERIFICACAO_PRECIPITACAO_INTERVALAR_ENSEMBLE_ASOF",
        "suporte_temporal": "ACUMULADO_INTERVALO_MM",
        "horizonte_horas": lead, "janela_acumulacao_horas": window,
        "passo_horas": step, "n": n, "membros": member_n,
        "primeiro_fim_intervalo_utc": (previous_valid - timedelta(hours=step * (n - 1))).isoformat(),
        "ultimo_fim_intervalo_utc": previous_valid.isoformat(),
        "antecedencia_minima_ao_inicio_horas": min(effective_lead),
        "limiar_mm": threshold, "eventos_observados": event_count,
        "frequencia_evento_observada": event_count / n,
        "brier": bs_sum / n, "brier_climatologia": ref_brier,
        "brier_skill_climatologia": 1 - bs_sum / bs_ref_sum if bs_ref_sum > 0 else None,
        "crps_medio_mm": crps_sum / n,
        "mae_media_ensemble_mm": absolute / n,
        "rmse_media_ensemble_mm": sqrt(sq_error / n),
        "bias_media_ensemble_mm": signed_error / n,
        "confiabilidade_por_faixas": [
            {"p_inicio": i / 10, "p_fim": (i + 1) / 10, "n": item["n"],
             "probabilidade_media": item["prob_total"] / item["n"] if item["n"] else None,
             "frequencia_observada": item["eventos"] / item["n"] if item["n"] else None}
            for i, item in enumerate(bins)
        ],
        "fonte_observacao": fonte_observacao,
        "fonte_climatologia": fonte_climatologia,
        "vintages_auditadas_externamente": False,
        "treino_independente_auditado": False,
        "calibracao_ensemble_validada": False,
        "homologado": False,
        "limites": ("A frequência de membros não é automaticamente probabilidade "
                    "calibrada; observação e previsão acumulam a mesma janela. "
                    "Metadata as-of autodeclarada exige RAW, SHA e ledger imutável. "
                    "Não usar hindcast feito depois dos fatos como previsão original. "
                    "Climatologia deve ser calculada sem incluir o período avaliado; "
                    "QC da estação e independência espaço-temporal exigem auditoria."),
    }
