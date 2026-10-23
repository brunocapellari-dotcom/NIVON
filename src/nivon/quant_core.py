"""NIVON: auditoria quantitativa comum, offline, por vintages e corte temporal.

Esta biblioteca nao treina modelo, nao coleta precos, nao valida licencas.
Compara previsoes previamente emitidas com resultados conhecidos depois;
todos os resultados permanecem NAO HOMOLOGADOS ate auditoria independente.
"""
from __future__ import annotations

from collections import defaultdict
from datetime import date, datetime, time, timezone
from math import isfinite, log, sqrt
from typing import Mapping, Sequence


class ErroQuantitativo(ValueError):
    """Quebra de contrato matematico, dimensional ou temporal."""


CATEGORIAS = ("ALTA", "ESTABILIDADE", "BAIXA")


def _instante(valor: object, campo: str) -> datetime:
    if not isinstance(valor, str) or "T" not in valor:
        raise ErroQuantitativo(f"{campo}: timestamp ISO 8601 com hora e fuso obrigatorio")
    try:
        dt = datetime.fromisoformat(valor.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ErroQuantitativo(f"{campo}: timestamp invalido") from exc
    if dt.tzinfo is None or dt.utcoffset() is None:
        raise ErroQuantitativo(f"{campo}: fuso obrigatorio")
    return dt.astimezone(timezone.utc)


def _dia(valor: object, campo: str) -> date:
    if not isinstance(valor, str):
        raise ErroQuantitativo(f"{campo}: data AAAA-MM-DD obrigatoria")
    try:
        d = date.fromisoformat(valor)
    except ValueError as exc:
        raise ErroQuantitativo(f"{campo}: data invalida") from exc
    if valor != d.isoformat():
        raise ErroQuantitativo(f"{campo}: data nao canonica")
    return d


def _numero(valor: object, campo: str, *, positivo: bool = False,
            nao_negativo: bool = False) -> float:
    if type(valor) not in (int, float):
        raise ErroQuantitativo(f"{campo}: numero explicito necessario")
    try:
        v = float(valor)
    except OverflowError as exc:
        raise ErroQuantitativo(f"{campo}: estouro numerico") from exc
    if not isfinite(v) or (positivo and v <= 0) or (nao_negativo and v < 0):
        raise ErroQuantitativo(f"{campo}: numero invalido")
    return v


def _identidade(valor: object, campo: str) -> str:
    if not isinstance(valor, str) or not valor.strip() or len(valor) > 128:
        raise ErroQuantitativo(f"{campo}: identificador invalido")
    return valor


def _hash(valor: object) -> str:
    if not isinstance(valor, str) or len(valor) != 64 or any(
            ch not in "0123456789abcdef" for ch in valor):
        raise ErroQuantitativo("edicao_sha256 invalido")
    return valor


def _calendario(calendario: Sequence[str]) -> tuple[list[date], dict[date, int]]:
    if not isinstance(calendario, (list, tuple)) or not 2 <= len(calendario) <= 100000:
        raise ErroQuantitativo("calendario de periodos invalido")
    dias = [_dia(s, "calendario") for s in calendario]
    if any(a >= b for a, b in zip(dias, dias[1:])):
        raise ErroQuantitativo("calendario duplicado ou fora de ordem")
    return dias, {d: i for i, d in enumerate(dias)}


def _periodo_validado(origem: date, alvo: date, mapa: Mapping[date, int],
                      horizonte: int) -> None:
    if origem not in mapa or alvo not in mapa or mapa[alvo] - mapa[origem] != horizonte:
        raise ErroQuantitativo("horizonte misto ou calendario incompatível")


def _parametros(horizonte: object, minimo: object) -> tuple[int, int]:
    if type(horizonte) is not int or not 1 <= horizonte <= 365:
        raise ErroQuantitativo("horizonte_periodos deve ser inteiro de 1 a 365")
    if type(minimo) is not int or minimo < 4:
        raise ErroQuantitativo("minimo de observacoes deve ser ao menos 4")
    return horizonte, minimo


def preparar_folds_asof(
    observacoes: Sequence[Mapping], *, calendario: Sequence[str],
    origens_em: Mapping[str, str], as_of_avaliacao: str,
    serie_id: str, unidade: str, fonte_id: str,
    horizonte_periodos: int, minimo_treino: int = 24,
) -> list[dict]:
    """Seleciona edicao observacional mais recente DISPONIVEL em cada origem.

    Exige calendario oficial/curado externo. O campo observado e fornecido para
    avaliar o fold, NUNCA para treinamento. Este preparador nao executa modelo.
    Se alguma origem/verdade nao puder ser comprovada, falha explicitamente.
    """
    horizonte, minimo = _parametros(horizonte_periodos, minimo_treino)
    dias, mapa = _calendario(calendario)
    avaliacao = _instante(as_of_avaliacao, "as_of_avaliacao")
    for nome, valor in (("serie_id", serie_id), ("unidade", unidade),
                        ("fonte_id", fonte_id)):
        _identidade(valor, nome)
    if not isinstance(observacoes, (list, tuple)) or not observacoes:
        raise ErroQuantitativo("observacoes ausentes")
    por_dia: dict[date, list[tuple[datetime, datetime, float, str]]] = defaultdict(list)
    vistos = set()
    for row in observacoes:
        if not isinstance(row, Mapping):
            raise ErroQuantitativo("observacao invalida")
        try:
            dia = _dia(row["periodo"], "periodo")
            publicacao = _instante(row["publicado_em"], "publicado_em")
            coleta = _instante(row["coletado_em"], "coletado_em")
            valor = _numero(row["valor"], "valor")
            digest = _hash(row["edicao_sha256"])
        except KeyError as exc:
            raise ErroQuantitativo(f"observacao sem campo {exc.args[0]}") from exc
        if any(row.get(k) != esperado for k, esperado in (
                ("serie_id", serie_id), ("unidade", unidade),
                ("fonte_id", fonte_id))):
            raise ErroQuantitativo("serie, unidade ou fonte misturadas no fold as-of")
        if dia not in mapa or not (publicacao <= coleta <= avaliacao):
            raise ErroQuantitativo("observacao fora do calendario/corte ou cronologia invalida")
        if publicacao < datetime.combine(dia, time.min, tzinfo=timezone.utc):
            raise ErroQuantitativo("publicacao anterior ao periodo observado")
        if (dia, coleta) in vistos:
            raise ErroQuantitativo("edicoes com mesmo periodo e instante de coleta")
        vistos.add((dia, coleta))
        por_dia[dia].append((coleta, publicacao, valor, digest))
    for versoes in por_dia.values():
        versoes.sort(key=lambda x: x[0])
    if not isinstance(origens_em, Mapping) or not origens_em:
        raise ErroQuantitativo("origens_em obrigatorio")
    saida = []
    for origem_s, emissao_s in sorted(origens_em.items()):
        origem = _dia(origem_s, "periodo_origem")
        if origem not in mapa:
            raise ErroQuantitativo("origem fora do calendario")
        i = mapa[origem]
        if i + horizonte >= len(dias) or i + 1 < minimo:
            raise ErroQuantitativo("origem sem treino suficiente ou alvo futuro no calendario")
        emissao = _instante(emissao_s, "emitido_em")
        alvo = dias[i + horizonte]
        if not (origem <= emissao.date() < alvo and emissao < avaliacao):
            raise ErroQuantitativo("emissao depois do alvo ou da avaliacao")
        treino = []
        for dia in dias[i + 1 - minimo:i + 1]:
            candidatas = [x for x in por_dia[dia] if x[0] <= emissao and x[1] <= emissao]
            if not candidatas:
                raise ErroQuantitativo(f"treino incompleto as-of na origem {origem}: {dia}")
            coleta, publicacao, valor, sha = candidatas[-1]
            treino.append({"periodo": dia.isoformat(), "valor": valor,
                           "disponivel_em": coleta.isoformat(),
                           "publicado_em": publicacao.isoformat(), "edicao_sha256": sha})
        candidatas_real = [x for x in por_dia[alvo] if x[0] <= avaliacao and x[1] <= avaliacao]
        if not candidatas_real:
            raise ErroQuantitativo(f"observado do alvo {alvo} indisponivel na avaliacao")
        coleta, publicacao, real, sha = candidatas_real[-1]
        saida.append({"periodo_origem": origem.isoformat(),
                      "emitido_em": emissao.isoformat(),
                      "alvo_periodo": alvo.isoformat(), "treino_asof": treino,
                      "real_avaliacao": real, "real_edicao_sha256": sha,
                      "real_publicado_em": publicacao.isoformat(),
                      "real_coletado_em": coleta.isoformat()})
    return saida


def _limiar(abs_tol: object, rel_tol: object, base: float) -> float:
    a = _numero(abs_tol, "tolerancia_absoluta", nao_negativo=True)
    r = _numero(rel_tol, "tolerancia_relativa", nao_negativo=True)
    if (a == 0 and r == 0) or r >= 1:
        raise ErroQuantitativo("banda positiva e percentual < 1 obrigatorios")
    limiar = a + abs(base) * r
    if not isfinite(limiar) or limiar <= 0:
        raise ErroQuantitativo("limiar fora do dominio numerico")
    return limiar


def _classe(delta: float, limiar: float) -> str:
    return "ALTA" if delta > limiar else ("BAIXA" if delta < -limiar else "ESTABILIDADE")


def avaliar_previsoes_oos(
    registros: Sequence[Mapping], *, calendario: Sequence[str],
    serie_id: str, modelo_id: str, unidade: str, baseline_id: str,
    horizonte_periodos: int, as_of_avaliacao: str,
    min_folds: int = 5, nao_negativo: bool = True,
    tolerancia_absoluta: float = 0.0,
    tolerancia_relativa: float = 0.0,
) -> dict:
    """Audita forecast archive de UMA serie, modelo, unidade e horizonte.

    Os metadados sao declarados pelo chamador; autenticidade dos logs/treino,
    calendario de pregões e direitos de dados demandam auditoria independente.
    Acuracia direcional e Brier somente com banda economica explicita.
    """
    horizonte, minimo = _parametros(horizonte_periodos, min_folds)
    dias, mapa = _calendario(calendario)
    limite = _instante(as_of_avaliacao, "as_of_avaliacao")
    for nome, valor in (("serie_id", serie_id), ("modelo_id", modelo_id),
                        ("unidade", unidade), ("baseline_id", baseline_id)):
        _identidade(valor, nome)
    if not isinstance(registros, (list, tuple)) or not minimo <= len(registros) <= 100000:
        raise ErroQuantitativo("folds OOS insuficientes ou em excesso")
    usa_prob = any("probabilidades" in r for r in registros if isinstance(r, Mapping))
    usa_intervalos = any(any(k in r for k in (
                        "intervalo_inferior", "intervalo_superior", "nivel_intervalo"))
                        for r in registros if isinstance(r, Mapping))
    if usa_prob:
        _limiar(tolerancia_absoluta, tolerancia_relativa, 1)
    vistos = set()
    erros, base_erros, abs_erros, abs_base, acertos = [], [], [], [], []
    scores, resultados, cobertura, larguras, niveis = [], [], [], [], set()
    confiabilidade = {c: [[] for _ in range(5)] for c in CATEGORIAS}
    for i, r in enumerate(registros):
        if not isinstance(r, Mapping):
            raise ErroQuantitativo(f"registro {i} nao e objeto")
        try:
            origem = _dia(r["periodo_origem"], "periodo_origem")
            alvo = _dia(r["alvo_periodo"], "alvo_periodo")
            emitido = _instante(r["emitido_em"], "emitido_em")
            dados = _instante(r["dados_disponiveis_ate"], "dados_disponiveis_ate")
            treino = _instante(r["treino_disponivel_ate"], "treino_disponivel_ate")
            publicado = _instante(r["observado_publicado_em"], "observado_publicado_em")
            coletado = _instante(r["observado_coletado_em"], "observado_coletado_em")
            _hash(r["edicao_sha256"])
            base = _numero(r["valor_base"], "valor_base", nao_negativo=nao_negativo)
            previsto = _numero(r["previsto"], "previsto", nao_negativo=nao_negativo)
            baseline = _numero(r["baseline"], "baseline", nao_negativo=nao_negativo)
            real = _numero(r["real"], "real", nao_negativo=nao_negativo)
        except KeyError as exc:
            raise ErroQuantitativo(f"registro {i} sem campo {exc.args[0]}") from exc
        _periodo_validado(origem, alvo, mapa, horizonte)
        if any(r.get(k) != esperado for k, esperado in (
                ("serie_id", serie_id), ("modelo_id", modelo_id),
                ("unidade", unidade), ("baseline_id", baseline_id),
                ("horizonte_periodos", horizonte))):
            raise ErroQuantitativo("mistura de modelos, series, unidades, baselines ou horizonte")
        if not (origem <= emitido.date() < alvo and
                dados <= emitido and treino <= emitido and
                emitido < datetime.combine(alvo, time.min, tzinfo=timezone.utc) <= publicado <= coletado <= limite):
            raise ErroQuantitativo("vazamento temporal, label ainda desconhecido ou cronologia invalida")
        chave = (origem, alvo)
        if chave in vistos:
            raise ErroQuantitativo("previsao repetida no mesmo alvo e origem")
        vistos.add(chave)
        e, eb = previsto - real, baseline - real
        if not isfinite(e) or not isfinite(eb):
            raise ErroQuantitativo("erro com overflow numerico")
        erros.append(e); base_erros.append(eb)
        abs_erros.append(abs(e)); abs_base.append(abs(eb))
        classe_real = None
        if usa_prob or tolerancia_absoluta or tolerancia_relativa:
            banda = _limiar(tolerancia_absoluta, tolerancia_relativa, base)
            classe_real = _classe(real - base, banda)
            acertos.append(_classe(previsto - base, banda) == classe_real)
        if usa_prob:
            probs = r.get("probabilidades")
            if not isinstance(probs, Mapping) or set(probs) != set(CATEGORIAS):
                raise ErroQuantitativo("probabilidades incompletas")
            ps = {c: _numero(probs[c], "probabilidade", nao_negativo=True)
                  for c in CATEGORIAS}
            if any(v > 1 for v in ps.values()) or abs(sum(ps.values()) - 1) > 1e-8:
                raise ErroQuantitativo("probabilidades fora de [0,1] ou nao somam 1")
            scores.append(sum((ps[c] - float(c == classe_real))**2 for c in CATEGORIAS) / 3)
            for c in CATEGORIAS:
                bin_i = min(4, int(ps[c] * 5))
                confiabilidade[c][bin_i].append((ps[c], float(c == classe_real)))
        if usa_intervalos:
            if not all(k in r for k in ("intervalo_inferior", "intervalo_superior", "nivel_intervalo")):
                raise ErroQuantitativo("intervalos incompletos em algum fold")
            lo = _numero(r["intervalo_inferior"], "intervalo_inferior",
                         nao_negativo=nao_negativo)
            hi = _numero(r["intervalo_superior"], "intervalo_superior",
                         nao_negativo=nao_negativo)
            nivel = _numero(r["nivel_intervalo"], "nivel_intervalo", positivo=True)
            if lo > hi or not 0 < nivel < 1:
                raise ErroQuantitativo("intervalo invertido ou nivel invalido")
            niveis.add(nivel)
            cobertura.append(lo <= real <= hi)
            larguras.append(hi - lo)
        resultados.append({"periodo_origem": origem.isoformat(),
                           "alvo_periodo": alvo.isoformat(),
                           "emitido_em": emitido.isoformat(),
                           "erro_modelo": e, "erro_baseline": eb,
                           "classe_real": classe_real,
                           "observado_publicado_em": publicado.isoformat(),
                           "observado_coletado_em": coletado.isoformat()})
    if len(niveis) > 1:
        raise ErroQuantitativo("niveis de intervalo misturados")
    n = len(registros)
    mae = sum(abs_erros) / n
    mae_base = sum(abs_base) / n
    rmse = sqrt(sum(e*e for e in erros)/n)
    rmse_base = sqrt(sum(e*e for e in base_erros)/n)
    if not all(isfinite(x) for x in (mae, mae_base, rmse, rmse_base, sum(erros)/n)):
        raise ErroQuantitativo("metrica com overflow numerico")
    bins = None
    if usa_prob:
        bins = {c: [
            {"n": len(linhas), "probabilidade_media": sum(p for p, _ in linhas)/len(linhas),
             "frequencia_observada": sum(y for _, y in linhas)/len(linhas)}
            for linhas in grupos if linhas] for c, grupos in confiabilidade.items()}
    return {
        "status": "AVALIACAO_OOS_DECLARADA_NAO_HOMOLOGADA",
        "serie_id": serie_id, "modelo_id": modelo_id, "unidade": unidade,
        "baseline_id": baseline_id, "horizonte_periodos": horizonte, "n_folds": n,
        "mae": mae, "rmse": rmse, "bias": sum(erros)/n,
        "mae_baseline": mae_base, "rmse_baseline": rmse_base,
        "ganho_mae_baseline": None if mae_base == 0 else 1 - mae/mae_base,
        "ganho_rmse_baseline": None if rmse_base == 0 else 1 - rmse/rmse_base,
        "acuracia_direcional": sum(acertos)/len(acertos) if acertos else None,
        "brier_multiclasse_medio": sum(scores)/len(scores) if scores else None,
        "confiabilidade_bins": bins,
        "cobertura_intervalo": sum(cobertura)/len(cobertura) if cobertura else None,
        "nivel_intervalo": next(iter(niveis)) if niveis else None,
        "largura_media_intervalo": sum(larguras)/len(larguras) if larguras else None,
        "folds": resultados, "calendario_externo_requer_homologacao": True,
        "vintages_e_logs_exigem_prova_externa": True, "publicavel": False,
        "aviso": "Metrica em arquivos declarados, nao prova OOS, calibracao, licenca ou skill em dados reais.",
    }


def tendencia_empirica_oos(
    novo: Mapping, residuos_historicos: Sequence[Mapping], *,
    calendario: Sequence[str], as_of: str, min_residuos: int = 30,
    tolerancia_absoluta: float = 0.0, tolerancia_relativa: float = 0.0,
) -> dict:
    """Distribuicao preditiva por erro historico OOS, NAO calibrada.

    Residuos da mesma serie/modelo/horizonte, REALMENTE conhecidos antes da
    emissao. Suavizacao de Laplace, sem assumir independência ou estabilidade.
    Bloqueia emitidos historicos retrospectivos com resultados futuros.
    """
    if not isinstance(novo, Mapping):
        raise ErroQuantitativo("nova previsao invalida")
    for campo in ("serie_id", "modelo_id", "unidade", "baseline_id"):
        _identidade(novo.get(campo), campo)
    horizonte, minimo = _parametros(novo.get("horizonte_periodos"), min_residuos)
    if minimo < 30:
        raise ErroQuantitativo("exigir ao menos 30 residuos OOS para probabilidade empirica")
    _, mapa = _calendario(calendario)
    origem = _dia(novo.get("periodo_origem"), "periodo_origem")
    alvo = _dia(novo.get("alvo_periodo"), "alvo_periodo")
    _periodo_validado(origem, alvo, mapa, horizonte)
    emissao = _instante(novo.get("emitido_em"), "emitido_em")
    corte = _instante(as_of, "as_of")
    usado = _instante(novo.get("dados_disponiveis_ate"), "dados_disponiveis_ate")
    treino = _instante(novo.get("treino_disponivel_ate"), "treino_disponivel_ate")
    if not (origem <= emissao.date() < alvo and emissao <= corte and
            usado <= emissao and treino <= emissao):
        raise ErroQuantitativo("previsao nova com vazamento temporal")
    base = _numero(novo.get("valor_base"), "valor_base")
    previsto = _numero(novo.get("previsto"), "previsto")
    limiar = _limiar(tolerancia_absoluta, tolerancia_relativa, base)
    avaliacao = avaliar_previsoes_oos(
        residuos_historicos, calendario=calendario,
        serie_id=novo["serie_id"], modelo_id=novo["modelo_id"],
        unidade=novo["unidade"], baseline_id=novo["baseline_id"],
        horizonte_periodos=horizonte, as_of_avaliacao=emissao.isoformat(),
        min_folds=minimo, nao_negativo=False,
    )
    contagem = {c: 0 for c in CATEGORIAS}
    for row in avaliacao["folds"]:
        residuo = -row["erro_modelo"]  # REAL - PREVISTO de historico OOS
        contagem[_classe(previsto + residuo - base, limiar)] += 1
    n = avaliacao["n_folds"]
    probs = {c: (contagem[c]+1)/(n+3) for c in CATEGORIAS}
    ranking = sorted(probs.items(), key=lambda x: x[1], reverse=True)
    classe = (ranking[0][0] if ranking[0][1] >= .60 and
              ranking[0][1] - ranking[1][1] >= .20 else "INDETERMINADA")
    return {
        "status": "PROBABILIDADES_EMPIRICAS_NAO_CALIBRADAS",
        "tendencia": classe, "orientacao": "PROJETADA",
        "probabilidades_empiricas_nao_calibradas": probs,
        "probabilidades_calibradas": None, "n_residuos": n,
        "modelo_id": novo["modelo_id"], "serie_id": novo["serie_id"],
        "unidade": novo["unidade"], "horizonte_periodos": horizonte,
        "alvo_periodo": alvo.isoformat(), "emitido_em": emissao.isoformat(),
        "limiar_unidade": limiar, "publicavel": False,
        "limitacao": "Pressupoe troca de residuos entre regimes; necessita proveniencia OOS, holdout, comparacao com climatologia, calibracao e licenca antes de publicar.",
    }
