"""Avaliação point-in-time de probabilidades direcionais de mercado.

Valida previsões emitidas antes da observação-alvo, rotulagem independente
por preços observados e benchmark expansivo apenas com desfechos disponíveis.
Não treina modelos e NÃO certifica calibração ou autorização de publicação.
"""
from __future__ import annotations

from collections import Counter
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from math import log
from typing import Mapping, Sequence


class ErroBacktestMercado(ValueError):
    pass


CLASSES = ("ALTA", "BAIXA", "ESTABILIDADE")


def _timestamp(v: object, nome: str) -> datetime:
    if not isinstance(v, str) or len(v) > 45:
        raise ErroBacktestMercado(f"{nome}: instante obrigatório")
    try:
        t = datetime.fromisoformat(v)
    except ValueError as exc:
        raise ErroBacktestMercado(f"{nome}: instante inválido") from exc
    if t.tzinfo is None or t.utcoffset() is None:
        raise ErroBacktestMercado(f"{nome}: fuso horário obrigatório")
    return t.astimezone(timezone.utc)


def _numero(v: object, nome: str, *, zero=False) -> Decimal:
    if type(v) not in (str, int, Decimal):
        raise ErroBacktestMercado(f"{nome}: decimal textual obrigatório")
    try:
        n = Decimal(str(v))
    except InvalidOperation as exc:
        raise ErroBacktestMercado(f"{nome}: não numérico") from exc
    if not n.is_finite() or len(n.as_tuple().digits) > 16 or (n < 0 if zero else n <= 0):
        raise ErroBacktestMercado(f"{nome}: valor inválido")
    return n


def _ident(v: object, nome: str) -> str:
    if not isinstance(v, str) or not v or len(v) > 120 or v.strip() != v:
        raise ErroBacktestMercado(f"{nome}: identidade inválida")
    return v


def _vetor(v: object) -> tuple[float, ...]:
    if not isinstance(v, Mapping) or set(v) != set(CLASSES):
        raise ErroBacktestMercado("probabilidades devem conter exatamente três classes")
    probs = [_numero(v[k], k, zero=True) for k in CLASSES]
    if abs(sum(probs) - 1) > Decimal("0.000001"):
        raise ErroBacktestMercado("probabilidades não somam um")
    return tuple(float(p) for p in probs)


def _rotulo(base: Decimal, alvo: Decimal, banda: Decimal) -> str:
    variacao = (alvo - base) / base
    return "ALTA" if variacao > banda else ("BAIXA" if variacao < -banda else "ESTABILIDADE")


def avaliar_probabilidades_tendencia(
    previsoes: Sequence[Mapping], *, as_of: str,
    minimo_historico: int = 20, minimo_avaliacao: int = 30,
) -> dict:
    """Brier multiclasses e benchmark prequential de frequência histórica.

    Cada linha exige preços base e alvo, disponibilidade verificável, um
    horizonte único e regra de banda declarada ANTES dos resultados. O
    benchmark em cada emissão observa apenas alvos coletados até esse instante.
    """
    corte = _timestamp(as_of, "as_of")
    if (not isinstance(previsoes, (tuple, list)) or len(previsoes) > 200000
            or type(minimo_historico) is not int or minimo_historico < 5
            or type(minimo_avaliacao) is not int or minimo_avaliacao < 10):
        raise ErroBacktestMercado("lote ou mínimos de avaliação inválidos")
    if len(previsoes) < minimo_historico + minimo_avaliacao:
        return {"status": "AMOSTRA_INSUFICIENTE", "avaliacoes": 0,
                "probabilidades_calibradas": None, "publicavel": False}
    normalizados = []
    identidade = set()
    visto = set()
    for obs in previsoes:
        if not isinstance(obs, Mapping):
            raise ErroBacktestMercado("linha inválida")
        try:
            serie = _ident(obs["serie_id"], "serie_id")
            versao = _ident(obs["modelo_versao"], "modelo_versao")
            regra = _ident(obs["regra_rotulagem"], "regra_rotulagem")
            emissao = _timestamp(obs["emitido_em"], "emitido_em")
            treino = _timestamp(obs["treinado_ate"], "treinado_ate")
            inicio = _timestamp(obs["base_referencia_em"], "base_referencia_em")
            base_disp = _timestamp(obs["base_disponivel_em"], "base_disponivel_em")
            alvo_t = _timestamp(obs["alvo_referencia_em"], "alvo_referencia_em")
            alvo_disp = _timestamp(obs["alvo_disponivel_em"], "alvo_disponivel_em")
            base = _numero(obs["valor_base"], "valor_base")
            alvo = _numero(obs["valor_alvo"], "valor_alvo")
            banda = _numero(obs["banda_relativa"], "banda_relativa", zero=True)
            horizonte = obs["horizonte_sessoes"]
            probs = _vetor(obs["probabilidades"])
            real = _ident(obs["classe_realizada"], "classe_realizada")
            hash_real = _ident(obs["edicao_real_sha256"], "edicao_real_sha256")
        except KeyError as exc:
            raise ErroBacktestMercado(f"campo ausente: {exc.args[0]}") from exc
        if type(horizonte) is not int or not 1 <= horizonte <= 252:
            raise ErroBacktestMercado("horizonte em sessões inválido")
        if banda >= 1 or len(hash_real) != 64 or any(c not in "0123456789abcdef" for c in hash_real):
            raise ErroBacktestMercado("limiar ou evidência inválidos")
        if not (inicio <= base_disp <= emissao < alvo_t <= alvo_disp <= corte
                and treino <= emissao):
            raise ErroBacktestMercado("look-ahead ou evidência temporal inválida")
        if real not in CLASSES or real != _rotulo(base, alvo, banda):
            raise ErroBacktestMercado("classe realizada inconsistente com preços e banda")
        identidade.add((serie, versao, regra, horizonte, str(banda)))
        chave = (serie, versao, emissao, alvo_t)
        if chave in visto:
            raise ErroBacktestMercado("previsão duplicada")
        visto.add(chave)
        normalizados.append((emissao, alvo_disp, real, probs))
    if len(identidade) != 1:
        raise ErroBacktestMercado("mistura de versão, mercado, banda, horizonte ou regra")
    normalizados.sort(key=lambda x: x[0])
    erros = []
    referencias = []
    logloss = []
    confiancas = []
    acertos = []
    for emissao, _, classe, probs in normalizados:
        disponiveis = [x[2] for x in normalizados if x[1] <= emissao]
        if len(disponiveis) < minimo_historico:
            continue
        frequencias = Counter(disponiveis)
        priori = [(frequencias.get(k, 0) + 1) / (len(disponiveis) + 3)
                  for k in CLASSES]
        obs_onehot = [float(k == classe) for k in CLASSES]
        erros.append(sum((p - v)**2 for p, v in zip(probs, obs_onehot)))
        referencias.append(sum((p - v)**2 for p, v in zip(priori, obs_onehot)))
        logloss.append(-log(max(probs[CLASSES.index(classe)], 1e-15)))
        maior = max(probs)
        confiancas.append(maior)
        acertos.append(float(CLASSES[probs.index(maior)] == classe))
    if len(erros) < minimo_avaliacao:
        return {"status": "AMOSTRA_OOS_INSUFICIENTE", "avaliacoes": len(erros),
                "probabilidades_calibradas": None, "publicavel": False}
    score = sum(erros) / len(erros)
    base_score = sum(referencias) / len(referencias)
    bins = []
    soma_calibracao = 0.0
    for a, b in ((0, .25), (.25, .5), (.5, .75), (.75, 1.0000001)):
        ids = [i for i, c in enumerate(confiancas) if a <= c < b]
        if not ids:
            continue
        conf = sum(confiancas[i] for i in ids) / len(ids)
        taxa = sum(acertos[i] for i in ids) / len(ids)
        bins.append({"faixa": [a, min(b, 1.0)], "n": len(ids),
                     "confianca_media": conf, "acerto": taxa})
        soma_calibracao += len(ids) / len(erros) * abs(conf - taxa)
    return {
        "status": "BACKTEST_TEMPORAL_OFFLINE_NAO_HOMOLOGADO",
        "serie_id": next(iter(identidade))[0],
        "modelo_versao": next(iter(identidade))[1],
        "regra_rotulagem": next(iter(identidade))[2],
        "horizonte_sessoes": next(iter(identidade))[3],
        "amostra_total": len(normalizados), "avaliacoes": len(erros),
        "brier_multiclasse": score, "brier_benchmark_expansivo": base_score,
        "skill_brier_vs_benchmark": 1 - score / base_score if base_score > 0 else None,
        "logloss_media": sum(logloss) / len(logloss),
        "ece_confianca": soma_calibracao, "bins_calibracao": bins,
        "probabilidades_calibradas": None, "publicavel": False,
        "limitacao": "Avaliação offline com rótulos declarados e prova temporal fornecida; "
                     "requer vintages independentes, dados reais, holdout e direitos antes de homologar.",
    }
