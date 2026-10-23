"""R03/R04: regressão E2E de backup SQLite sob concorrência.

Todos os dados e caminhos são temporários; processos reais, sem mocks,
rede, serviços remotos ou recursos produtivos.
"""
from __future__ import annotations

import multiprocessing
import queue
import sqlite3
import tempfile
import unittest
from pathlib import Path

from nivon.backup_sqlite import criar_backup, restaurar_backup


def _escritor_em_wal(caminho: str, iniciou, pode_confirmar, saida):
    db = None
    try:
        db = sqlite3.connect(caminho, timeout=2)
        db.execute("BEGIN IMMEDIATE")
        db.execute("INSERT INTO movimentos VALUES (2, 200)")
        iniciou.set()
        if not pode_confirmar.wait(12):
            raise TimeoutError("escritor não recebeu sinal de commit")
        db.commit()
        saida.put(("OK", None))
    except BaseException as exc:
        saida.put((type(exc).__name__, str(exc)))
    finally:
        if db is not None:
            db.close()


def _backup_de_conexao_escritora(caminho: str, destino: str, iniciou, saida):
    conn = None
    try:
        conn = sqlite3.connect(caminho, timeout=0.25)
        conn.execute("BEGIN IMMEDIATE")
        conn.execute("INSERT INTO movimentos VALUES (3, 300)")
        iniciou.set()
        result = criar_backup(conn, destino)
        saida.put(("SUCESSO_INDEVIDO", result["integridade"]))
    except BaseException as exc:
        saida.put(("REJEITADO", f"{type(exc).__name__}: {exc}"))
    finally:
        if conn is not None:
            conn.rollback()
            conn.close()


class TestAuditoriaBackupConcorrente(unittest.TestCase):
    def test_backup_wal_durante_transacao_de_outro_escritor_e_consistente(self):
        ctx = multiprocessing.get_context("spawn")
        with tempfile.TemporaryDirectory(prefix="nivon-audit-wal-") as temp:
            origem = str(Path(temp) / "origem.sqlite")
            copia = str(Path(temp) / "copia.sqlite")
            restaurado = str(Path(temp) / "restaurado.sqlite")
            with sqlite3.connect(origem) as db:
                modo = db.execute("PRAGMA journal_mode=WAL").fetchone()[0]
                self.assertEqual(modo.lower(), "wal")
                db.execute("CREATE TABLE movimentos(id INTEGER PRIMARY KEY, valor INTEGER)")
                db.execute("INSERT INTO movimentos VALUES (1, 100)")
                db.commit()

            iniciou = ctx.Event()
            pode_confirmar = ctx.Event()
            saida = ctx.Queue()
            p = ctx.Process(target=_escritor_em_wal,
                            args=(origem, iniciou, pode_confirmar, saida))
            try:
                p.start()
                self.assertTrue(iniciou.wait(8), "escritor não entrou na transação")
                with sqlite3.connect(origem, timeout=4) as leitura:
                    registro = criar_backup(leitura, copia)
                restaurar_backup(copia, restaurado, sha256_esperado=registro["sha256"])
            finally:
                pode_confirmar.set()
                p.join(timeout=12)
                if p.is_alive():
                    p.terminate()
                    p.join(timeout=3)
                saida.close()
                saida.join_thread()

            self.assertFalse(p.is_alive(), "escritor WAL travou")
            self.assertEqual(p.exitcode, 0)
            with sqlite3.connect(restaurado) as db:
                rows = db.execute("SELECT * FROM movimentos ORDER BY id").fetchall()
                self.assertEqual(rows, [(1, 100)],
                                 "backup deve conter só dados confirmados")
                self.assertEqual(db.execute("PRAGMA integrity_check").fetchone()[0],
                                 "ok")
            with sqlite3.connect(origem) as db:
                rows = db.execute("SELECT * FROM movimentos ORDER BY id").fetchall()
                self.assertEqual(rows, [(1, 100), (2, 200)])

    def test_backup_de_conexao_com_transacao_de_escrita_aberta_recusa_sem_travar(self):
        ctx = multiprocessing.get_context("spawn")
        with tempfile.TemporaryDirectory(prefix="nivon-audit-open-tx-") as temp:
            origem = str(Path(temp) / "origem.sqlite")
            copia = str(Path(temp) / "copia.sqlite")
            with sqlite3.connect(origem) as db:
                db.execute("CREATE TABLE movimentos(id INTEGER PRIMARY KEY, valor INTEGER)")
                db.execute("INSERT INTO movimentos VALUES (1, 100)")
                db.commit()

            iniciou = ctx.Event()
            saida = ctx.Queue()
            p = ctx.Process(target=_backup_de_conexao_escritora,
                            args=(origem, copia, iniciou, saida))
            try:
                p.start()
                self.assertTrue(iniciou.wait(8), "não abriu transação de escrita")
                p.join(timeout=4)
                travou = p.is_alive()
                if travou:
                    p.terminate()
                    p.join(timeout=3)
                mensagem = None
                if not travou:
                    try:
                        mensagem = saida.get(timeout=1)
                    except queue.Empty:
                        mensagem = ("SEM_RESULTADO", "")
                self.assertFalse(
                    travou,
                    "P0: criar_backup chamou sqlite3.Connection.backup a partir "
                    "de uma conexão com INSERT não confirmado e não retornou "
                    "dentro de 4s; exige preflight/recusa fail-closed",
                )
                self.assertEqual(
                    mensagem[0], "REJEITADO",
                    "P0: backup de transação de escrita aberta deve falhar "
                    "explicitamente, não salvar estado ambíguo",
                )
            finally:
                if p.is_alive():
                    p.terminate()
                    p.join(timeout=3)
                saida.close()
                saida.join_thread()


if __name__ == "__main__":
    unittest.main()
