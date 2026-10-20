"""Series e baselines pecuarios com vintages e corte temporal estrito.

Uma serie = uma especie, indicador, unidade, praca e fonte. Modelo sazonal
e comparado com persistencia, sem probabilidades inventadas ou promocao.
"""
from __future__ import annotations

from datetime import datetime, timezone
from math import isfinite, sqrt
import re
from statistics import median

from .motores import DadoInvalido

MERCADOS = {
    "BOVINO": {"BOI_GORDO": "BRL_ARROBA_CARCACA", "BEZERRO": "BRL_CABECA"},
    "FRANGO": {"FRANGO_VIVO": "BRL_KG_VIVO"},
    "SUINO": {"SUINO_VIVO": "BRL_KG_VIVO"},
}


def _instante(valor):
    if not isinstance(valor, str):
        raise DadoInvalido("timestamp nao textual")
    try:
        d = datetime.fromisoformat(valor.replace("Z", "+00:00"))
    except ValueError as exc:
        raise DadoInvalido("timestamp invalido") from exc
    if d.tzinfo is None or d.utcoffset() is None:
        raise DadoInvalido("fuso obrigatorio")
    return d.astimezone(timezone.utc)


def _mes(valor):
    if not isinstance(valor, str) or not re.fullmatch(r"20\d{2}-(0[1-9]|1[0-2])", valor):
        raise DadoInvalido("competencia mensal YYYY-MM obrigatoria")
    return 12 * int(valor[:4]) + int(valor[5:7])


def _exigir_identidade(obs, *, especie, indicador, unidade, praca, fonte_id):
    for k, v in (("especie", especie), ("indicador", indicador), ("unidade", unidade),
                 ("praca", praca), ("fonte_id", fonte_id)):
        if obs.get(k) != v:
            raise DadoInvalido("serie heterogenea em " + k)


def selecionar_vintage_precos(*, serie, especie, indicador, praca, fonte_id, corte_asof):
    """Retorna um valor por mes conhecido ate corte, nunca revisoes futuras.

    Serie previamente adquirida com direitos. Data de coleta representa
    disponibilidade para este banco: backfill atual nao cria vintages antigos.
    """
    if especie not in MERCADOS or indicador not in MERCADOS[especie]:
        raise DadoInvalido("especie/mercado nao suportados")
    unidade = MERCADOS[especie][indicador]
    if any(not isinstance(x, str) or not x.strip() for x in (praca, fonte_id)):
        raise DadoInvalido("praca e fonte obrigatorias")
    corte = _instante(corte_asof)
    if not isinstance(serie, (tuple, list)) or len(serie) > 1200:
        raise DadoInvalido("serie ausente ou acima do limite")
    edicoes = {}
    for obs in serie:
        if not isinstance(obs, dict):
            raise DadoInvalido("observacao deve ser objeto")
        _exigir_identidade(obs, especie=especie, indicador=indicador,
                           unidade=unidade, praca=praca, fonte_id=fonte_id)
        mes = _mes(obs.get("competencia"))
        referencia = obs.get("data_referencia")
        if not isinstance(referencia, str) or not re.fullmatch(r"20\d{2}-(0[1-9]|1[0-2])-(0[1-9]|[12]\d|3[01])", referencia):
            raise DadoInvalido("data_referencia YYYY-MM-DD obrigatoria")
        try:
            ref_dt = datetime.fromisoformat(referencia).replace(tzinfo=timezone.utc)
        except ValueError as exc:
            raise DadoInvalido("data_referencia invalida") from exc
        if 12 * ref_dt.year + ref_dt.month != mes:
            raise DadoInvalido("referencia fora da competencia")
        if type(obs.get("valor")) not in (int, float) or not isfinite(obs["valor"]) or obs["valor"] <= 0:
            raise DadoInvalido("preco deve ser positivo finito")
        sha = obs.get("origem_sha256")
        if not isinstance(sha, str) or not re.fullmatch(r"[a-f0-9]{64}", sha):
            raise DadoInvalido("SHA256 de origem obrigatorio")
        pub, coleta = _instante(obs.get("publicacao")), _instante(obs.get("coleta"))
        if pub > coleta or ref_dt > pub:
            raise DadoInvalido("cronologia referencia/publicacao/coleta incoerente")
        if mes > 12 * corte.year + corte.month:
            continue
        if pub > corte or coleta > corte:
            continue
        atual = edicoes.get(mes)
        chave = (pub, coleta)
        if atual is None or chave > atual[0]:
            edicoes[mes] = (chave, obs)
        elif chave == atual[0] and (obs["valor"] != atual[1]["valor"] or sha != atual[1]["origem_sha256"]):
            raise DadoInvalido("edicoes conflitantes sem ordenacao temporal")
    return {mes: float(info[1]["valor"]) for mes, info in edicoes.items()}


def tendencia_observada_pecuaria(*, serie, especie, indicador, praca,
                                fonte_id, corte_asof, limiar_pct=3.0):
    """Mediana de tres variacoes homomes anuais, so com 15 meses contiguos."""
    if type(limiar_pct) not in (float, int) or not isfinite(limiar_pct) or not 0 < limiar_pct <= 50:
        raise DadoInvalido("limiar percentual invalido")
    dados = selecionar_vintage_precos(serie=serie, especie=especie, indicador=indicador,
        praca=praca, fonte_id=fonte_id, corte_asof=corte_asof)
    ultimo = max(dados) if dados else None
    base = {"especie": especie, "indicador": indicador, "praca": praca,
        "unidade": MERCADOS[especie][indicador], "fonte_id": fonte_id,
        "n_meses_disponiveis": len(dados), "corte_asof": corte_asof,
        "tendencia": "INDETERMINADA", "variacao_homomes_mediana_pct": None,
        "probabilidade_alta": None, "probabilidade_baixa": None,
        "previsao_homologada": False, "classificacao": "TENDENCIA_HISTORICA_OBSERVADA"}
    if ultimo is None or any((ultimo - i) not in dados for i in range(15)):
        return base
    variacoes = [100 * (dados[ultimo-i] / dados[ultimo-i-12] - 1) for i in range(3)]
    percentual = median(variacoes)
    direcao = "ALTA" if percentual > limiar_pct else "BAIXA" if percentual < -limiar_pct else "ESTAVEL"
    return {**base, "competencia_final": f"{(ultimo-1)//12:04d}-{(ultimo-1)%12+1:02d}",
            "valor_final": dados[ultimo], "variacao_homomes_mediana_pct": percentual,
            "tendencia": direcao}


def backtest_sazonal_pecuaria(*, serie, especie, indicador, praca,
                             fonte_id, corte_asof):
    """Walk-forward mensal com disponibilidade historica, sem leakage.

    Para cada mes alvo, previsao feita no PRIMEIRO instante UTC do mes.
    Baselines: mes homologo anterior e ultimo mes disponivel. Requisito:
    pelo menos 12 folds validos, sem imputar observacoes ausentes.
    """
    corte = _instante(corte_asof)
    final = selecionar_vintage_precos(serie=serie, especie=especie, indicador=indicador,
        praca=praca, fonte_id=fonte_id, corte_asof=corte_asof)
    erros_sazonais, erros_persistencia = [], []
    for alvo in sorted(final):
        ano, mes = divmod(alvo - 1, 12)
        inicio = f"{ano:04d}-{mes+1:02d}-01T00:00:00+00:00"
        if alvo >= 12 * corte.year + corte.month:
            continue
        disponivel = selecionar_vintage_precos(serie=serie, especie=especie,
            indicador=indicador, praca=praca, fonte_id=fonte_id, corte_asof=inicio)
        if alvo - 12 not in disponivel or alvo - 1 not in disponivel:
            continue
        realizado = final[alvo]
        erros_sazonais.append(realizado - disponivel[alvo - 12])
        erros_persistencia.append(realizado - disponivel[alvo - 1])
    n = len(erros_sazonais)
    if n < 12:
        return {"especie": especie, "indicador": indicador, "folds_validos": n,
                "avaliavel": False, "previsao_homologada": False,
                "motivo": "menos de 12 folds sem vazamento temporal"}
    mae = sum(abs(x) for x in erros_sazonais) / n
    mae_base = sum(abs(x) for x in erros_persistencia) / n
    rmse = sqrt(sum(x*x for x in erros_sazonais) / n)
    return {"especie": especie, "indicador": indicador, "folds_validos": n,
            "mae_sazonal": mae, "rmse_sazonal": rmse,
            "mae_persistencia": mae_base, "ganho_relativo_mae": 1 - mae/mae_base if mae_base else None,
            "avaliavel": True, "previsao_homologada": False,
            "probabilidades_calibradas": False,
            "classificacao": "BACKTEST_OFFLINE_BASELINE",
            "limitacao": "Sem janela de avaliacao independente, custo de dados ou calibracao probabilistica."}
