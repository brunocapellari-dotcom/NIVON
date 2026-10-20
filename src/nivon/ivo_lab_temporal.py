"""Laboratório temporal IVO: treinamento leve e walk-forward estritamente as-of.

Treina o peso de um candidato de mistura entre duas referências ingênuas,
usando somente observações e revisões conhecidas em cada emissão histórica.
Não faz coleta, RAG, treinamento de LLM, promoção ou publicação operacional.
"""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from hashlib import sha256
from math import isfinite
from statistics import mean

from .historico import Observacao, visao_na_data


class ErroLab(ValueError):
    pass


def _mes(periodo: str) -> date:
    if not isinstance(periodo, str) or len(periodo) != 7:
        raise ErroLab("competência mensal AAAA-MM obrigatória")
    try:
        d = date.fromisoformat(periodo + "-01")
    except ValueError as exc:
        raise ErroLab("competência mensal AAAA-MM inválida") from exc
    if d.strftime("%Y-%m") != periodo:
        raise ErroLab("competência fora do padrão canônico")
    return d


def _avancar(data: date, n: int) -> date:
    x = data.year * 12 + data.month - 1 + n
    return date(x // 12, x % 12 + 1, 1)


def _corte(competencia: date) -> datetime:
    """Um instante antes de começar o mês alvo, no calendário UTC."""
    return datetime(competencia.year, competencia.month, 1, tzinfo=timezone.utc) - timedelta(microseconds=1)


def _validar_corte(instante: datetime) -> datetime:
    if not isinstance(instante, datetime) or instante.tzinfo is None or instante.utcoffset() is None:
        raise ErroLab("data de corte timezone-aware obrigatória")
    return instante.astimezone(timezone.utc)


def _texto(valor: str, nome: str) -> str:
    if not isinstance(valor, str) or not valor.strip() or len(valor) > 160:
        raise ErroLab(f"{nome} inválido")
    return valor


def _base(
    observacoes: list[Observacao], *, fonte: str, variavel: str,
    produto: str, regiao: str, unidade: str
) -> list[Observacao]:
    for nome, valor in (("fonte", fonte), ("variavel", variavel),
                        ("produto", produto), ("regiao", regiao), ("unidade", unidade)):
        _texto(valor, nome)
    if not isinstance(observacoes, (list, tuple)):
        raise ErroLab("lista de evidências inválida")
    registros = []
    for o in observacoes:
        if not isinstance(o, Observacao):
            raise ErroLab("observação canônica inválida")
        if (o.fonte, o.variavel, o.produto, o.regiao, o.unidade) != (
                fonte, variavel, produto, regiao, unidade):
            continue
        if o.calendario != "MENSAL" or o.natureza != "OBSERVADO":
            raise ErroLab("não utilizar estimativas, projeções ou calendário não mensal no treino")
        _mes(o.competencia)
        if not isfinite(o.valor) or o.valor < 0:
            raise ErroLab("valor negativo ou inválido no treino")
        registros.append(o)
    if not registros:
        raise ErroLab("nenhum histórico observado compatível")
    return registros


def _snapshot(registros: list[Observacao], corte: datetime) -> dict[str, Observacao]:
    corte = _validar_corte(corte)
    selecionadas = visao_na_data(
        registros, data_corte_publicacao=corte.date(),
        instante_corte_coleta=corte,
    )
    return {o.competencia: o for o in selecionadas if o.referencia <= corte.date()}


def _features(registros: list[Observacao], alvo: date) -> dict | None:
    corte = _corte(alvo)
    dados = _snapshot(registros, corte)
    antigo = _avancar(alvo, -12).strftime("%Y-%m")
    sazonal = dados.get(antigo)
    recentes = sorted(
        (o for p, o in dados.items() if _mes(p) < alvo),
        key=lambda o: o.competencia,
    )
    if sazonal is None or not recentes:
        return None
    ultimo = recentes[-1]
    def distancia(a: date, b: date) -> int:
        return (a.year - b.year) * 12 + a.month - b.month
    lag = distancia(alvo, _mes(ultimo.competencia))
    if not 1 <= lag <= 3:
        return None
    return {
        "sazonal": float(sazonal.valor), "ultimo_conhecido": float(ultimo.valor),
        "lag_recente_meses": lag, "sazonal_periodo": antigo,
        "ultimo_periodo": ultimo.competencia,
        "ultima_coleta": max(sazonal.coleta, ultimo.coleta).isoformat(),
        "corte": corte.isoformat(),
    }


def _aprender(registros: list[Observacao], alvo: date, *,
              minimo_treino: int, regularizacao: float) -> dict:
    """Treino supervisionado em pares já publicados antes do corte do alvo.

    Cada vetor histórico de características é reconstruído no corte daquela
    previsão histórica, nunca a partir da série atualizada em retrospecto.
    """
    corte = _corte(alvo)
    verdades_disponiveis = _snapshot(registros, corte)
    inicio = min(_mes(p) for p in verdades_disponiveis) if verdades_disponiveis else alvo
    pares = []
    competencias_treino = []
    cursor = _avancar(inicio, 12)
    while cursor < alvo:
        competencia = cursor.strftime("%Y-%m")
        real = verdades_disponiveis.get(competencia)
        if real is not None:
            f = _features(registros, cursor)
            if f is not None:
                pares.append((f["sazonal"], f["ultimo_conhecido"], float(real.valor)))
                competencias_treino.append(competencia)
        cursor = _avancar(cursor, 1)
    if len(pares) < minimo_treino:
        raise ErroLab("histórico supervisionado as-of insuficiente")
    distancias = [recent - sazonal for sazonal, recent, _ in pares]
    soma_quadrados = sum(d * d for d in distancias)
    numerador = sum(d * (real - sazonal) for d, (sazonal, _, real) in zip(distancias, pares))
    coef = numerador / ((1 + regularizacao) * soma_quadrados) if soma_quadrados else 0.
    peso = min(1., max(0., coef))
    return {"peso_recente": peso, "peso_sazonal": 1-peso,
            "amostras_treino": len(pares),
            "primeira_competencia_treino": competencias_treino[0],
            "ultima_competencia_treino": competencias_treino[-1],
            "status": "CANDIDATO_NAO_HOMOLOGADO"}


def prever_asof(
    observacoes: list[Observacao], *, periodo_alvo: str, fonte: str,
    variavel: str, produto: str, regiao: str, unidade: str,
    minimo_treino: int = 6, regularizacao: float = 0.05
) -> dict:
    alvo = _mes(periodo_alvo)
    if type(minimo_treino) is not int or not 3 <= minimo_treino <= 120:
        raise ErroLab("minimo_treino deve ser inteiro entre 3 e 120")
    if (isinstance(regularizacao, bool) or not isinstance(regularizacao, (int, float))
            or not isfinite(regularizacao) or regularizacao < 0):
        raise ErroLab("regularização inválida")
    registros = _base(observacoes, fonte=fonte, variavel=variavel,
                      produto=produto, regiao=regiao, unidade=unidade)
    f = _features(registros, alvo)
    if f is None:
        raise ErroLab("baseline sazonal ou observação recente indisponível no corte")
    treino = _aprender(registros, alvo, minimo_treino=minimo_treino,
                      regularizacao=regularizacao)
    peso = treino["peso_recente"]
    previsao = (1-peso)*f["sazonal"] + peso*f["ultimo_conhecido"]
    h = sha256(
        repr((periodo_alvo, fonte, variavel, produto, regiao, unidade,
              f, treino, round(previsao, 12))).encode("utf-8")
    ).hexdigest()
    return {
        "estado": "CANDIDATO_NAO_HOMOLOGADO", "metodo": "BLEND_RIDGE_RESTRITO",
        "periodo": periodo_alvo, "fonte": fonte, "variavel": variavel,
        "produto": produto, "regiao": regiao, "unidade": unidade,
        "emitida_em": _corte(alvo).isoformat(),
        "features_asof": f, "treino": treino,
        "previsao": previsao, "baseline_sazonal": f["sazonal"],
        "checksum_evidencia": h, "modelo_homologado": False,
        "explicacao": ("Peso de mistura treinado sobre observações conhecidas; "
                       "não prova causalidade nem desempenho fora da amostra."),
    }


def walkforward_asof(
    observacoes: list[Observacao], *, fonte: str, variavel: str,
    produto: str, regiao: str, unidade: str, inicio: str, fim: str,
    minimo_treino: int = 6, regularizacao: float = 0.05
) -> dict:
    começo, final = _mes(inicio), _mes(fim)
    if final < começo or (final.year-começo.year)*12+final.month-começo.month > 120:
        raise ErroLab("janela walk-forward inválida ou superior a 121 meses")
    regs = _base(observacoes, fonte=fonte, variavel=variavel,
                 produto=produto, regiao=regiao, unidade=unidade)
    resultados, ignorados = [], []
    instante_avaliacao = _corte(_avancar(final, 2))
    retrospecto = _snapshot(regs, instante_avaliacao)
    corrente = começo
    while corrente <= final:
        periodo = corrente.strftime("%Y-%m")
        try:
            p = prever_asof(regs, periodo_alvo=periodo, fonte=fonte,
                            variavel=variavel, produto=produto, regiao=regiao,
                            unidade=unidade, minimo_treino=minimo_treino,
                            regularizacao=regularizacao)
        except ErroLab as exc:
            ignorados.append({"periodo": periodo, "motivo": str(exc)})
            corrente = _avancar(corrente, 1)
            continue
        verdade = retrospecto.get(periodo)
        if verdade is None:
            ignorados.append({"periodo": periodo, "motivo": "resultado final não disponível até data de avaliação"})
        else:
            # O resultado só é utilizado aqui, depois de feita a previsão.
            resultados.append({
                "periodo": periodo, "previsto": p["previsao"],
                "baseline": p["baseline_sazonal"], "observado": float(verdade.valor),
                "erro_absoluto": abs(p["previsao"]-verdade.valor),
                "erro_baseline": abs(p["baseline_sazonal"]-verdade.valor),
                "treino_amostras": p["treino"]["amostras_treino"],
                "treino_peso_recente": p["treino"]["peso_recente"],
                "checksum_evidencia": p["checksum_evidencia"],
                "emitida_em": p["emitida_em"],
                "observacao_publicada_em": verdade.publicacao.isoformat(),
            })
        corrente = _avancar(corrente, 1)
    num = len(resultados)
    em = sum(p["erro_absoluto"] for p in resultados)
    eb = sum(p["erro_baseline"] for p in resultados)
    return {
        "estado": "BACKTEST_OFFLINE_NAO_HOMOLOGADO", "fonte": fonte,
        "variavel": variavel, "produto": produto, "regiao": regiao, "unidade": unidade,
        "folds": resultados, "ignorados": ignorados, "folds_validos": num,
        "mae_modelo": em/num if num else None,
        "mae_baseline": eb/num if num else None,
        "melhora_baseline": em < eb if num else None,
        "promocao_automatica": False,
        "limite": "Amostra retrospectiva e declaração temporal não homologam dados reais ou modelo em produção.",
    }
