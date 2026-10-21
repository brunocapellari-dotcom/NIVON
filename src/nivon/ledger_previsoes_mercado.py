"""Ledger SQLite de previsões: append-only lógico, não WORM físico.

Nenhum agendamento, rede, segredo ou conexão externa. Conexão fornecida pelo
operador. Para segurança real, assinar/exportar cada cabeça para âncora
independente com timestamp, backup/restauração e ACL testados.
"""
from __future__ import annotations

import json
import sqlite3
from typing import Mapping

from .proveniencia_previsoes_mercado import (
    GENESIS, ErroRegistroPrevisao, _canonico, _hora,
    criar_registro_previsao, verificar_cadeia_previsoes,
)


class ErroLedgerPrevisao(ErroRegistroPrevisao):
    """Falha em append, âncora externa, ordem temporal ou corrupção."""


def inicializar_ledger(con: sqlite3.Connection) -> None:
    """Cria apenas estruturas locais. Triggers impedem UPDATE/DELETE pela API SQL.

    Não impede DROP TABLE, edição do arquivo por usuário privilegiado,
    adulteração do relógio ou recomposição criptográfica de toda a cadeia.
    """
    if not isinstance(con, sqlite3.Connection):
        raise ErroLedgerPrevisao("conexão SQLite obrigatória")
    con.executescript("""
        CREATE TABLE IF NOT EXISTS nivon_previsoes_ledger (
            sequencia INTEGER PRIMARY KEY AUTOINCREMENT,
            previsao_id TEXT NOT NULL UNIQUE,
            registro_em TEXT NOT NULL,
            anterior_sha256 TEXT NOT NULL,
            registro_sha256 TEXT NOT NULL UNIQUE,
            registro_json TEXT NOT NULL
        );
        CREATE TRIGGER IF NOT EXISTS nivon_previsoes_sem_update
        BEFORE UPDATE ON nivon_previsoes_ledger
        BEGIN SELECT RAISE(ABORT, 'append_only_previsao'); END;
        CREATE TRIGGER IF NOT EXISTS nivon_previsoes_sem_delete
        BEFORE DELETE ON nivon_previsoes_ledger
        BEGIN SELECT RAISE(ABORT, 'append_only_previsao'); END;
    """)


def _carregar(con: sqlite3.Connection) -> list[dict]:
    linhas = con.execute(
        "SELECT sequencia, previsao_id, registro_em, anterior_sha256, "
        "registro_sha256, registro_json FROM nivon_previsoes_ledger "
        "ORDER BY sequencia ASC"
    ).fetchall()
    registros = []
    for n, (seq, pid, instante, anterior, digest, raw) in enumerate(linhas, 1):
        if seq != n:
            raise ErroLedgerPrevisao("sequência do ledger rompida")
        try:
            obj = json.loads(raw)
        except (TypeError, ValueError) as exc:
            raise ErroLedgerPrevisao("JSON do ledger corrompido") from exc
        if not isinstance(obj, dict) or (
            _canonico(obj).decode("utf-8") != raw or
            obj.get("previsao", {}).get("previsao_id") != pid or
            obj.get("previsao", {}).get("registrado_em") != instante or
            obj.get("anterior_sha256") != anterior or
            obj.get("registro_sha256") != digest
        ):
            raise ErroLedgerPrevisao("metadados do ledger inconsistentes")
        registros.append(obj)
    return registros


def consultar_ledger(con: sqlite3.Connection, *, cabeca_esperada_sha256: str) -> dict:
    """Confere integridade com a cabeça recebida de fonte independente.

    A origem da âncora é responsabilidade do operador; passar valor obtido
    do próprio banco não constitui prova externa de imutabilidade.
    """
    from .proveniencia_previsoes_mercado import _hash
    _hash(cabeca_esperada_sha256, "cabeca_esperada_sha256")
    registros = _carregar(con)
    if not registros:
        if cabeca_esperada_sha256 != GENESIS:
            raise ErroLedgerPrevisao("cabeça externa diverge de ledger vazio")
        return {"status": "LEDGER_VAZIO", "registros": [],
                "cabeca_sha256": GENESIS, "publicavel": False}
    verificado = verificar_cadeia_previsoes(
        registros, cabeca_esperada_sha256=cabeca_esperada_sha256
    )
    return {"status": "LEDGER_HASH_CONFERIDO_OFFLINE",
            "registros": registros, "cabeca_sha256": verificado["cabeca_sha256"],
            "quantidade": len(registros), "publicavel": False,
            "ancora_externa_autenticada": False}


def anexar_previsao(
    con: sqlite3.Connection, previsao: dict, *, cabeca_atual_esperada_sha256: str,
) -> dict:
    """Grava 1 evento em transação exclusiva; nunca substitui previsão prévia.

    Exige âncora da cabeça **anterior** para detectar rollback/truncamento
    antes do append. A nova cabeça deve ser exportada/ancorada externamente
    pelo operador ANTES de permitir outro ciclo confiável.
    """
    if not isinstance(con, sqlite3.Connection):
        raise ErroLedgerPrevisao("conexão SQLite obrigatória")
    if con.in_transaction:
        raise ErroLedgerPrevisao("conexão já possui transação pendente")
    try:
        con.execute("BEGIN IMMEDIATE")
        atual = consultar_ledger(con,
                                cabeca_esperada_sha256=cabeca_atual_esperada_sha256)
        if atual["registros"]:
            ultimo = atual["registros"][-1]["previsao"]
            if _hora(previsao.get("registrado_em"), "registrado_em") < _hora(
                ultimo["registrado_em"], "registrado_em"
            ):
                raise ErroLedgerPrevisao("registro temporal retroativo")
        novo = criar_registro_previsao(
            previsao, anterior_sha256=cabeca_atual_esperada_sha256)
        con.execute(
            "INSERT INTO nivon_previsoes_ledger "
            "(previsao_id, registro_em, anterior_sha256, registro_sha256, registro_json) "
            "VALUES (?, ?, ?, ?, ?)",
            (previsao["previsao_id"], previsao["registrado_em"],
             cabeca_atual_esperada_sha256, novo["registro_sha256"],
             _canonico(novo).decode("utf-8")),
        )
        con.commit()
        return {"status": "APPEND_SQLITE_LOCAL_SEM_ANCORA_REMOTA",
                "registro_sha256": novo["registro_sha256"],
                "previsao_id": previsao["previsao_id"],
                "ancora_externa_autenticada": False, "publicavel": False}
    except (sqlite3.Error, ValueError, TypeError, KeyError) as exc:
        con.rollback()
        if isinstance(exc, ErroRegistroPrevisao):
            raise
        raise ErroLedgerPrevisao("falha transacional no ledger") from exc
