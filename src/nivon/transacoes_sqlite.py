"""Savepoints SQLite aninhados para garantir atomicidade de ledger + agregado.

Context managers de sqlite3.Connection fazem COMMIT da transação inteira e
não são apropriados quando o chamador já abriu uma operação maior.
"""
from __future__ import annotations

from contextlib import contextmanager
from uuid import uuid4


@contextmanager
def savepoint_atomico(db):
    """Confirma apenas o próprio savepoint, preservando transação externa."""
    nome = "nivon_sp_" + uuid4().hex
    db.execute("SAVEPOINT " + nome)
    try:
        yield
    except BaseException:
        db.execute("ROLLBACK TO SAVEPOINT " + nome)
        db.execute("RELEASE SAVEPOINT " + nome)
        raise
    else:
        db.execute("RELEASE SAVEPOINT " + nome)
