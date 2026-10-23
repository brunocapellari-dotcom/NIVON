"""Orquestração do lote PTAX: captura -> RAW SQLite -> auditoria.

Chamada explícita, SEM scheduler nem rede por padrão, sem publicação
ou deploy. Todas as janelas executam em um único savepoint SQLite.
Uma falha cancela TUDO, inclusive novas tabelas criadas no lote.
"""
from __future__ import annotations

from datetime import datetime
import sqlite3
from typing import Callable, Mapping

from .captura_ptax_http import capturar_ptax_odata
from .continuidade_ptax import auditar_integridade_ptax
from .ptax_plano import planejar_consultas_ptax
from .ptax_odata_bruta_mercados import _consulta
from .ptax_raw_sqlite import guardar_raw_ptax
from .transacoes_sqlite import savepoint_atomico


class ErroLotePTAX(ValueError):
    """Entrada, transação ou cobertura do lote PTAX inválida."""


def executar_lote_ptax(
    db: sqlite3.Connection, catalogo: dict, *, planos: list[dict],
    permitir_rede: bool = False,
    autorizacoes: frozenset[str] = frozenset(),
    evidencia_direitos: str | None = None,
    transporte_injetado: Callable | None = None,
    relogio: Callable[[], datetime] | None = None,
) -> dict:
    """Execução transacional completa; dados sintéticos nunca operacionais.

    O chamador configura o armazenamento SQLite e o catálogo. Não cria
    agendamento, publica dados, libera licença ou agenda reexecuções.
    """
    if not isinstance(db, sqlite3.Connection) or not isinstance(catalogo, dict):
        raise ErroLotePTAX("banco ou catálogo inválido")
    if type(permitir_rede) is not bool or type(planos) is not list or (
        not 1 <= len(planos) <= 20):
        raise ErroLotePTAX("lote exige 1-20 consultas, rede booleana")
    if transporte_injetado is not None and (
        not callable(transporte_injetado) or permitir_rede
    ):
        raise ErroLotePTAX("transporte de teste não é coleta real")
    if transporte_injetado is None and not permitir_rede:
        raise PermissionError("lote sem transporte injetado exige opt-in de rede")
    if transporte_injetado is not None and (
        autorizacoes or evidencia_direitos is not None
    ):
        raise ErroLotePTAX("simulação não pode reivindicar direitos de coleta real")
    pares = set()
    for plano in planos:
        if not isinstance(plano, dict):
            raise ErroLotePTAX("plano não é objeto")
        try:
            moeda = plano["moeda"]
            inicio, fim = _consulta(plano["url"], moeda)
            contrato = planejar_consultas_ptax(
                moeda=moeda, inicio=inicio.isoformat(),
                fim=fim.isoformat(), dias_janela=(fim-inicio).days+1,
            )
        except (KeyError, TypeError, ValueError, IndexError) as exc:
            raise ErroLotePTAX("plano inválido") from exc
        if len(contrato) != 1 or contrato[0] != plano:
            raise ErroLotePTAX("plano divergente do planejador")
        identidade = (moeda, inicio, fim)
        if identidade in pares:
            raise ErroLotePTAX("janela duplicada no lote")
        pares.add(identidade)
    resultados = []
    with savepoint_atomico(db):
        for plano in planos:
            captura = capturar_ptax_odata(
                plano, permitir_rede=permitir_rede, catalogo=catalogo,
                autorizacoes=autorizacoes,
                evidencia_direitos=evidencia_direitos,
                transporte=transporte_injetado,
                relogio=relogio,
            )
            guardado = guardar_raw_ptax(
                db, catalogo, captura, autorizacoes=autorizacoes,
                evidencia_direitos=evidencia_direitos,
            )
            resultados.append({
                "moeda": plano["moeda"],
                "inicio": plano["inicio"], "fim": plano["fim"],
                "sha256": guardado["sha256"],
                "capturado_em": guardado["coleta"],
                "boletins": guardado["boletins"],
                "nova_versao_snapshot": guardado["nova_versao_snapshot"],
                "nova_captura": guardado["nova_captura"],
                "adotou_snapshot_legado": guardado["adotou_snapshot_legado"],
            })
        inventario = auditar_integridade_ptax(db)
    return {
        "status": "LOTE_PTAX_INGESTAO_LOCAL_VALIDADA_SEM_PUBLICACAO",
        "tipo": "REAL_AUTORIZADO" if permitir_rede else "SINTETICO",
        "consultas_concluidas": len(resultados),
        "boletins_processados": sum(x["boletins"] for x in resultados),
        "resultados": resultados,
        "inventario": inventario,
        "rede_ativada_por_este_comando": permitir_rede,
        "registro_de_publicacao_comprovado": False,
        "apto_backtest_por_publicacao": False,
        "publicavel": False,
    }
