"""Auditoria ponta a ponta offline de uma previsão já emitida.

NÃO executa scraper, coleta, assinatura, agendamento ou modelo preditivo.
O E2E fecha vínculos INTERNOS entre ledger, recibo MAC, snapshots de
preços (bytes originais + linhas JSONL) e calendário declarado. Não
comprova que o parser converteu corretamente o fornecedor nem autentica
origem, hora certificada, licença ou armazenamento WORM.
"""
from __future__ import annotations

import sqlite3
from typing import Mapping

from .ancora_previsoes_mercado import auditar_ledger_com_recibo
from .evidencia_bruta_mercados import (
    _lote_jsonl_conferido, preparar_precos_com_artefatos,
)
from .ledger_previsoes_mercado import consultar_ledger
from .proveniencia_previsoes_mercado import (
    _texto, reconciliar_previsao,
)


class ErroAuditoriaMercado(ValueError):
    """Input ausente ou previsão não presente no ledger auditado."""


PACOTE = frozenset({"arquivo_original", "snapshot_jsonl", "manifesto"})


def _validar_pacote(pacote: object, *, corte: str) -> tuple[list[dict], dict]:
    if not isinstance(pacote, Mapping) or set(pacote) != PACOTE:
        raise ErroAuditoriaMercado("pacote raw/JSONL/manifesto inválido")
    prova = preparar_precos_com_artefatos(
        pacote["arquivo_original"], pacote["snapshot_jsonl"],
        manifesto=pacote["manifesto"], as_of=corte,
    )
    # Consome exatamente o MESMO byte buffer que foi comparado ao digest.
    linhas = _lote_jsonl_conferido(pacote["snapshot_jsonl"])
    return linhas, prova["evidencia_arquivos"]


def auditar_previsao_ponta_a_ponta(
    con: sqlite3.Connection, *, previsao_id: str,
    recibo_ancora: Mapping, ledger_id: str, segredo_verificacao: bytes,
    pacote_base: Mapping, pacote_alvo: Mapping, calendario_sessoes: Mapping,
    as_of: str,
) -> dict:
    """Audita 1 previsão do ledger até a classificação realizada (offline).

    Cabeça e sequência devem corresponder ao MAC confiado, incluindo
    todos os registros até o último. Pacote BASE precisa estar capturado
    ANTES DA EMISSÃO, e pacote ALVO antes do corte da avaliação.
    """
    _texto(previsao_id, "previsao_id")
    prova_ancora = auditar_ledger_com_recibo(
        con, recibo=recibo_ancora, ledger_id=ledger_id,
        segredo_verificacao=segredo_verificacao, as_of=as_of,
    )
    ledger = consultar_ledger(
        con, cabeca_esperada_sha256=prova_ancora["cabeca_sha256"]
    )
    achadas = [x for x in ledger["registros"]
               if x["previsao"]["previsao_id"] == previsao_id]
    if len(achadas) != 1:
        raise ErroAuditoriaMercado("previsão não encontrada ou duplicada")
    registro = achadas[0]
    emitido_em = registro["previsao"]["emitido_em"]
    base, prova_base = _validar_pacote(pacote_base, corte=emitido_em)
    alvo, prova_alvo = _validar_pacote(pacote_alvo, corte=as_of)
    reconciliado = reconciliar_previsao(
        registro, cadeia=ledger["registros"],
        cabeca_esperada_sha256=prova_ancora["cabeca_sha256"],
        precos_base=base, precos_alvo=alvo,
        calendario_sessoes=calendario_sessoes, as_of=as_of,
    )
    return {
        "status": "E2E_INTERNO_CONFERIDO_OFFLINE_NAO_HOMOLOGADO",
        "previsao_id": previsao_id,
        "recibo_mac_conferido": prova_ancora["mac_conferido"],
        "cabeca_sha256": prova_ancora["cabeca_sha256"],
        "arquivo_base_sha256": prova_base["raw_sha256"],
        "snapshot_base_sha256": prova_base["normalizado_sha256"],
        "arquivo_alvo_sha256": prova_alvo["raw_sha256"],
        "snapshot_alvo_sha256": prova_alvo["normalizado_sha256"],
        "serie_fingerprint_sha256": reconciliado["serie_fingerprint_sha256"],
        "item_backtest": reconciliado["item_backtest"],
        "parser_independente_verificado": False,
        "origem_mercado_autenticada": False,
        "anchorage_worm_comprovada": False,
        "licenca_publicacao_verificada": False,
        "publicavel": False,
        "probabilidades_calibradas": None,
    }


def auditar_previsao_ponta_a_ponta_csv_canonico(
    con: sqlite3.Connection, *, previsao_id: str,
    recibo_ancora: Mapping, ledger_id: str, segredo_verificacao: bytes,
    pacote_base: Mapping, pacote_alvo: Mapping, calendario_sessoes: Mapping,
    as_of: str,
) -> dict:
    """Extensão rígida: 1:1 raw CSV canônico x JSONL antes do backtest.

    O CSV aqui é contrato de ENSAIO NIVON, não documento oficial
    CME/ICE. A validação independe do parser que produziu JSONL, mas
    não homologa esse parser para formatos oficiais ou dados live.
    """
    from .auditoria_extracao_csv_mercados import verificar_extracao_csv_canonico

    # O fluxo original verifica ANTES a cadeia, o recibo e a consistência
    # temporal; ambos os artefatos são inspecionados novamente de forma
    # estrita, sob os MESMOS bytes e instantes econômicos.
    result = auditar_previsao_ponta_a_ponta(
        con, previsao_id=previsao_id, recibo_ancora=recibo_ancora,
        ledger_id=ledger_id, segredo_verificacao=segredo_verificacao,
        pacote_base=pacote_base, pacote_alvo=pacote_alvo,
        calendario_sessoes=calendario_sessoes, as_of=as_of,
    )
    corte_base = result["item_backtest"]["emitido_em"]
    conferidos = []
    for pacote, corte in ((pacote_base, corte_base), (pacote_alvo, as_of)):
        conferidos.append(verificar_extracao_csv_canonico(
            pacote["arquivo_original"], pacote["snapshot_jsonl"],
            manifesto=pacote["manifesto"], as_of=corte,
        )["evidencia_extracao_csv"])
    return {
        **result,
        "status": "E2E_CSV_CANONICO_CONFERIDO_OFFLINE_NAO_HOMOLOGADO",
        "extracao_csv_canonico_conferida": True,
        "linhas_base_conferidas": conferidos[0]["registros_conferidos"],
        "linhas_alvo_conferidas": conferidos[1]["registros_conferidos"],
        # Não confundir contrato CSV NIVON com o formato do fornecedor.
        "parser_independente_verificado": False,
        "parser_oficial_mercado_validado": False,
        "origem_mercado_autenticada": False,
        "licenca_publicacao_verificada": False,
        "publicavel": False,
        "probabilidades_calibradas": None,
    }
