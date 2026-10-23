"""Savepoints SQLite com lock antecipado em novas transações.

Em conexão externa já transacionada, preserva a responsabilidade do chamador.
Em conexão sem transação, BEGIN IMMEDIATE evita read-then-write concorrente
e COMMIT somente do bloco próprio após RELEASE do savepoint.
"""
from __future__ import annotations

from contextlib import contextmanager
from uuid import uuid4


@contextmanager
def savepoint_atomico(db):
    """Atomicidade do bloco, sem confirmar transação aberta pelo chamador."""
    dono_da_transacao = not db.in_transaction
    if dono_da_transacao:
        # O lock de escrita deve ser obtido ANTES do SELECT/INSERT do ledger.
        # O timeout/busy_timeout da conexão define a espera, sem spin loop.
        db.execute("BEGIN IMMEDIATE")
    nome = "nivon_sp_" + uuid4().hex
    try:
        db.execute("SAVEPOINT " + nome)
        try:
            yield
        except BaseException:
            db.execute("ROLLBACK TO SAVEPOINT " + nome)
            db.execute("RELEASE SAVEPOINT " + nome)
            raise
        else:
            db.execute("RELEASE SAVEPOINT " + nome)
        if dono_da_transacao:
            db.commit()
    except BaseException:
        if dono_da_transacao and db.in_transaction:
            db.rollback()
        raise
