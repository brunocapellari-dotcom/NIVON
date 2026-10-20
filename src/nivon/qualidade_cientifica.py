"""Verificadores científicos puros: unidades, conservação e avaliação temporal.

Não executa coleta, não estima parâmetros de mercado, não homologa previsão e não
autoriza publicação. Erro metodológico => exceção; erro numérico => parecer reprovado.
"""
from __future__ import annotations

from datetime import datetime
from math import isfinite, sqrt
from typing import Mapping, Sequence


class ErroCientifico(ValueError):
    pass


def numero(valor: object, nome: str, *, nao_negativo: bool = True) -> float:
    """Rejeita bool, NaN, infinito e unidades implícitas em texto."""
    if type(valor) not in (int, float) or not isfinite(valor):
        raise ErroCientifico(f"{nome}: valor numérico finito obrigatório")
    valor = float(valor)
    if nao_negativo and valor < 0:
        raise ErroCientifico(f"{nome}: valor físico negativo")
    return valor


def identidade_safra(
    *, area_colhida_ha: float, produtividade_kg_ha: float,
    producao_reportada_t: float, resolucao_area_ha: float,
    resolucao_produtividade_kg_ha: float, resolucao_producao_t: float,
) -> dict:
    """Tolerância conservadora de arredondamento propagado; sem ajuste silencioso."""
    area = numero(area_colhida_ha, "area_colhida_ha")
    rendimento = numero(produtividade_kg_ha, "produtividade_kg_ha")
    producao = numero(producao_reportada_t, "producao_reportada_t")
    a = numero(resolucao_area_ha, "resolucao_area_ha")
    y = numero(resolucao_produtividade_kg_ha, "resolucao_produtividade_kg_ha")
    p = numero(resolucao_producao_t, "resolucao_producao_t")
    if min(a, y, p) <= 0 or area == 0:
        raise ErroCientifico("resoluções e área devem ser positivas")
    calculada = area * rendimento / 1000
    # Limite superior por multiplicação de dois intervalos arredondados.
    arredondamento = ((area + a/2) * (rendimento + y/2) - area*rendimento)/1000 + p/2
    residuo = producao - calculada
    return {
        "equacao": "producao_t = area_colhida_ha * produtividade_kg_ha / 1000",
        "producao_calculada_t": calculada,
        "residuo_t": residuo,
        "tolerancia_arredondamento_t": arredondamento,
        "consistente": abs(residuo) <= arredondamento + 1e-12,
        "status": "VERIFICACAO_FISICA_NAO_HOMOLOGACAO",
    }


def balanco_massa(
    *, estoque_inicial_t: float, producao_t: float, importacao_t: float,
    consumo_t: float, exportacao_t: float, perdas_t: float,
    estoque_final_t: float, ajuste_estatistico_t: float = 0,
    tolerancia_documentada_t: float = 0,
) -> dict:
    """O ajuste estatístico é visível; nunca força o fechamento."""
    numeros = {
        "estoque_inicial_t": estoque_inicial_t, "producao_t": producao_t,
        "importacao_t": importacao_t, "consumo_t": consumo_t,
        "exportacao_t": exportacao_t, "perdas_t": perdas_t,
        "estoque_final_t": estoque_final_t,
    }
    vals = {k: numero(v, k) for k, v in numeros.items()}
    ajuste = numero(ajuste_estatistico_t, "ajuste_estatistico_t", nao_negativo=False)
    tol = numero(tolerancia_documentada_t, "tolerancia_documentada_t")
    ofertas = vals["estoque_inicial_t"] + vals["producao_t"] + vals["importacao_t"]
    usos = vals["consumo_t"] + vals["exportacao_t"] + vals["perdas_t"] + vals["estoque_final_t"]
    residuo = ofertas - usos - ajuste
    return {
        "oferta_total_t": ofertas, "uso_e_estoque_total_t": usos,
        "ajuste_estatistico_expresso_t": ajuste,
        "residuo_nao_explicado_t": residuo,
        "consistente": abs(residuo) <= tol + 1e-12,
        "status": "BALANCO_AUDITADO_NAO_HOMOLOGADO",
    }


def _instante(valor: str, nome: str) -> datetime:
    if not isinstance(valor, str):
        raise ErroCientifico(f"{nome}: ISO 8601 obrigatório")
    try:
        data = datetime.fromisoformat(valor.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ErroCientifico(f"{nome}: timestamp inválido") from exc
    if data.tzinfo is None or data.utcoffset() is None:
        raise ErroCientifico(f"{nome}: exige fuso")
    return data


def auditar_backtest_temporal(
    folds: Sequence[Mapping[str, object]], *,
    min_folds: int = 5, serie_nao_negativa: bool = True,
) -> dict:
    """Um passo adiante: dados disponíveis <= emissão < competência observada.

    Espera chaves: emitido_em, disponivel_ate, baseline_disponivel_em,
    observado_em, real, previsto, baseline. Entradas são pré-agregadas;
    a rotina não consegue provar que o treinamento externo foi correto.
    """
    if type(min_folds) is not int or min_folds < 5:
        raise ErroCientifico("mínimo de cinco folds, não adulterável para baixo")
    if not isinstance(folds, (list, tuple)) or len(folds) < min_folds:
        raise ErroCientifico("folds fora da amostra insuficientes")
    vistos = set()
    erros, bases, quadrados, quadrados_base = [], [], [], []
    for indice, f in enumerate(folds):
        if not isinstance(f, Mapping):
            raise ErroCientifico("fold não é mapeamento")
        try:
            emitido = _instante(f["emitido_em"], "emitido_em")
            disponivel = _instante(f["disponivel_ate"], "disponivel_ate")
            base_data = _instante(f["baseline_disponivel_em"], "baseline_disponivel_em")
            observado = _instante(f["observado_em"], "observado_em")
            real = numero(f["real"], "real", nao_negativo=serie_nao_negativa)
            previsto = numero(f["previsto"], "previsto", nao_negativo=serie_nao_negativa)
            baseline = numero(f["baseline"], "baseline", nao_negativo=serie_nao_negativa)
        except KeyError as exc:
            raise ErroCientifico(f"fold {indice}: campo obrigatório ausente") from exc
        if not (disponivel <= emitido and base_data <= emitido < observado):
            raise ErroCientifico(f"fold {indice}: vazamento temporal")
        if observado in vistos:
            raise ErroCientifico("observação repetida no mesmo horizonte avaliado")
        vistos.add(observado)
        erro = abs(real-previsto)
        erro_base = abs(real-baseline)
        erros.append(erro);bases.append(erro_base)
        quadrados.append(erro**2);quadrados_base.append(erro_base**2)
    n = len(folds)
    mae = sum(erros)/n
    mae_b = sum(bases)/n
    rmse = sqrt(sum(quadrados)/n)
    rmse_b = sqrt(sum(quadrados_base)/n)
    return {
        "n_folds": n, "mae_modelo": mae, "mae_baseline": mae_b,
        "rmse_modelo": rmse, "rmse_baseline": rmse_b,
        "ganho_mae": None if mae_b == 0 else (mae_b-mae)/mae_b,
        "ganho_rmse": None if rmse_b == 0 else (rmse_b-rmse)/rmse_b,
        "melhor_mae_e_rmse": mae < mae_b and rmse < rmse_b,
        "status": "ESTATISTICA_OFFLINE_SEM_HOMOLOGACAO_DE_VINTAGES_REAIS",
        "autoriza_publicacao_preditiva": False,
    }
