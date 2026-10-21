"""Comparação offline dos caminhos PTAX legado(float) e RAW Decimal.

Este componente é uma barreira de migração: NUNCA muda o briefing nem
transforma uma prova de paridade numérica em licença, autenticidade da
fonte ou publicação histórica comprovada. Tabelas ficam inalteradas.
"""
from __future__ import annotations

from decimal import Decimal, InvalidOperation
import re
import sqlite3
from typing import Mapping

from .indicador_ptax import indicador_ptax_sqlite
from .indicadores_historicos import _direitos
from .ptax_historico_decimal import selecionar_ptax_decimal_asof
from .qualidade_mercados import _momento


class ErroParidadePTAX(ValueError):
    """Resultado da comparação inválido ou inconsistente."""


_DISPLAY = re.compile(
    r"compra R\$ ([0-9]{1,10}),([0-9]{4}); venda R\$ ([0-9]{1,10}),([0-9]{4})\Z"
)
_CASA = Decimal("0.0001")
_ELEGIVEL_ANTIGO = "INDICADOR_VERIFICADO_TEMPO"
_ELEGIVEL_NOVO = "PTAX_DECIMAL_ASOF_CONFERIDA_OFFLINE"


def _parsear_legado(d: Mapping) -> tuple[Decimal, Decimal]:
    indicador = d.get("indicador")
    if not isinstance(indicador, Mapping):
        raise ErroParidadePTAX("indicador legado ausente")
    valor = indicador.get("valor")
    achado = _DISPLAY.fullmatch(valor) if isinstance(valor, str) else None
    if not achado:
        raise ErroParidadePTAX("formatação PTAX legada não reconhecida")
    return (Decimal(achado[1] + "." + achado[2]),
            Decimal(achado[3] + "." + achado[4]))


def _parsear_raw(txt: object) -> Decimal:
    if (not isinstance(txt, str) or len(txt) > 40 or
            not re.fullmatch(r"[0-9]+(?:\.[0-9]+)?", txt)):
        raise ErroParidadePTAX("cotação Decimal bruta inválida")
    try:
        v = Decimal(txt)
    except InvalidOperation as exc:
        raise ErroParidadePTAX("cotação Decimal bruta inválida") from exc
    if not v.is_finite() or v <= 0 or len(v.as_tuple().digits) > 16:
        raise ErroParidadePTAX("cotação Decimal bruta inválida")
    return v


def _bloquear(codigo: str, motivos: list[str], *, antigo: Mapping, novo: Mapping) -> dict:
    return {
        "status": codigo, "motivos": motivos,
        "estado_legado": antigo.get("status"),
        "estado_decimal": novo.get("status"),
        "comparacao_numerica_confirmada": False,
        "mesma_edicao_raw_comprovada": False,
        "substituicao_automatica_autorizada": False,
        "apto_backtest_por_publicacao": False,
        "publicavel": False,
    }


def comparar_indicadores_ptax(
    antigo: Mapping, novo: Mapping, *, moeda: str = "USD",
) -> dict:
    """Compara os dois caminhos por categoria, timestamp e precisão exata.

    Aceita estruturas em memória para permitir fixtures de ensaio; isso
    NÃO autentica nenhum dos dois resultados. Não declara a migração apta.
    """
    if moeda not in ("USD", "EUR"):
        raise ErroParidadePTAX("moeda inválida")
    if not isinstance(antigo, Mapping) or not isinstance(novo, Mapping):
        raise ErroParidadePTAX("comparação requer duas evidências")
    if antigo.get("status") != _ELEGIVEL_ANTIGO or novo.get("status") != _ELEGIVEL_NOVO:
        return _bloquear(
            "COMPARACAO_INCOMPLETA", ["ao menos uma fonte não entregou boletim elegível"],
            antigo=antigo, novo=novo,
        )
    evid = antigo.get("evidencia")
    ind = antigo.get("indicador")
    if not isinstance(evid, Mapping) or not isinstance(ind, Mapping):
        raise ErroParidadePTAX("proveniencia legada ausente")
    if (evid.get("dataset_id") != "BCB_PTAX"
            or ind.get("fonte_id") != "BCB_PTAX"
            or novo.get("moeda") != moeda
            or ind.get("secao") != "CAMBIO"
            or ind.get("titulo") is None
            or not isinstance(ind.get("titulo"), str)
            or not ind["titulo"].startswith(f"PTAX {moeda}/BRL")):
        return _bloquear(
            "DIVERGENCIA_PTAX_BLOQUEADA", ["origem ou moeda divergem"],
            antigo=antigo, novo=novo,
        )
    motivos = []
    try:
        old_ref = _momento(evid["data_hora_cotacao"], "referencia_antiga")
        ind_ref = _momento(ind["referencia"], "referencia_indicador")
        new_ref = _momento(novo["referencia_em"], "referencia_nova")
        old_col = _momento(evid["coleta"], "coleta_antiga")
        new_col = _momento(novo["primeira_coleta_conhecida"], "coleta_nova")
    except (KeyError, ValueError, TypeError) as exc:
        raise ErroParidadePTAX("temporalidade das evidências inválida") from exc
    if old_ref != new_ref or ind_ref != old_ref:
        motivos.append("referencia_temporal")
    if old_ref > old_col or new_ref > new_col:
        motivos.append("coleta_anterior_a_cotacao")
    old_tipo = evid.get("tipo_boletim")
    new_tipo = novo.get("tipo_boletim")
    if old_tipo != new_tipo:
        motivos.append("tipo_boletim")
    expected_tipo = "FECHAMENTO" if new_tipo == "Fechamento" else "OUTRO_BOLETIM"
    if (evid.get("tipo_selecionado") != expected_tipo or
            novo.get("tipo_selecionado") !=
            ("FECHAMENTO" if new_tipo == "Fechamento"
             else "BOLETIM_SEM_FECHAMENTO_COMPROVADO")):
        motivos.append("classificacao_boletim")
    if evid.get("classe") != "REAL_AUTORIZADO" or novo.get("origem_tipo") != "REAL_AUTORIZADO":
        motivos.append("classe_nao_real")
    if any(x is not None for x in (
            evid.get("publicacao"), novo.get("probabilidades_calibradas"))):
        motivos.append("metadados_nao_esperados")
    if antigo.get("evidencia", {}).get("apto_backtest_por_publicacao") is not False or (
            novo.get("apto_backtest_por_publicacao") is not False
    ):
        motivos.append("alegacao_publicacao_sem_prova")
    ocompra, ovenda = _parsear_legado(antigo)
    ncompra = _parsear_raw(novo.get("compra_decimal"))
    nvenda = _parsear_raw(novo.get("venda_decimal"))
    if any((v != v.quantize(_CASA)) for v in (ncompra, nvenda)):
        motivos.append("precisao_decimal_superior_ao_legado")
    if ocompra != ncompra:
        motivos.append("cotacao_compra")
    if ovenda != nvenda:
        motivos.append("cotacao_venda")
    if motivos:
        return _bloquear("DIVERGENCIA_PTAX_BLOQUEADA",
                         sorted(set(motivos)), antigo=antigo, novo=novo)
    sha_old = evid.get("sha256_original")
    sha_new = novo.get("raw_sha256")
    if (not isinstance(sha_old, str) or not isinstance(sha_new, str) or
            not re.fullmatch("[0-9a-f]{64}", sha_old) or
            not re.fullmatch("[0-9a-f]{64}", sha_new)):
        raise ErroParidadePTAX("SHA de proveniencia inválido")
    mesmos_bytes = sha_old == sha_new
    mesma_coleta = old_col == new_col
    return {
        "status": ("PARIDADE_NUMERICA_MESMA_EDICAO_OFFLINE" if mesmos_bytes and mesma_coleta
                   else "PARIDADE_NUMERICA_SEM_MESMA_EDICAO_COMPROVADA"),
        "motivos": ([] if mesmos_bytes and mesma_coleta
                    else ["edicao_ou_coleta_distinta"]),
        "moeda": moeda, "referencia_em": new_ref.isoformat(),
        "tipo_boletim": new_tipo,
        "comparacao_numerica_confirmada": True,
        "mesma_edicao_raw_comprovada": mesmos_bytes and mesma_coleta,
        "sha_legado": sha_old, "sha_decimal": sha_new,
        "coleta_legada": old_col.isoformat(),
        "primeira_coleta_raw": new_col.isoformat(),
        "substituicao_automatica_autorizada": False,
        "apto_backtest_por_publicacao": False,
        "publicavel": False,
    }


def auditar_migracao_ptax(
    db_legado: sqlite3.Connection, db_raw: sqlite3.Connection, *,
    gerado_em: str, fontes: dict, moeda: str = "USD",
    idade_maxima_horas: int = 168,
) -> dict:
    """Executa comparação read-only; nunca alimenta briefing ou publica.

    Os dois bancos podem ser o mesmo, desde que as edições e schemas
    sejam distintos e consistentes com o ledger canônico.
    """
    if not isinstance(db_legado, sqlite3.Connection) or not isinstance(db_raw, sqlite3.Connection):
        raise ErroParidadePTAX("duas conexões SQLite obrigatórias")
    if moeda not in ("USD", "EUR") or type(idade_maxima_horas) is not int or (
            not 1 <= idade_maxima_horas <= 336):
        raise ErroParidadePTAX("parametros inválidos")
    if not isinstance(fontes, dict) or not _direitos(fontes, "BCB_PTAX"):
        return _bloquear(
            "BLOQUEADO_DIREITOS", ["direitos de leitura e publicação derivada ausentes"],
            antigo={}, novo={},
        )
    # Métodos legados em operação continuam exatamente como estavam.
    velho = indicador_ptax_sqlite(
        db_legado, gerado_em=gerado_em, fontes=fontes, moeda=moeda,
        idade_maxima_horas=idade_maxima_horas,
    )
    novo = selecionar_ptax_decimal_asof(
        db_raw, corte=gerado_em, moeda=moeda,
        incluir_sinteticos=False, idade_maxima_horas=idade_maxima_horas,
    )
    return comparar_indicadores_ptax(velho, novo, moeda=moeda)
