import os
import sqlite3
import tempfile
import unittest
from pathlib import Path

from nivon.backup_sqlite import ErroBackup, criar_backup, restaurar_backup


class TestBackupLocal(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name)
        self.conn = sqlite3.connect(":memory:")
        self.addCleanup(self.conn.close)
        self.conn.execute("CREATE TABLE precos (id INTEGER PRIMARY KEY, valor INTEGER)")
        self.conn.execute("INSERT INTO precos VALUES (1, 125)")
        self.conn.commit()
        self.arquivo = self.path / "copia.sqlite"

    def test_backup_valido_sha_e_integridade(self):
        r = criar_backup(self.conn, self.arquivo)
        self.assertEqual(len(r["sha256"]), 64)
        self.assertEqual(r["integridade"], "OK")
        self.assertTrue(self.arquivo.exists())

    def test_restaurar_dados_corretos(self):
        b = criar_backup(self.conn, self.arquivo)
        destino = self.path / "restaurado.sqlite"
        x = restaurar_backup(self.arquivo, destino, sha256_esperado=b["sha256"])
        self.assertEqual(x["integridade"], "OK")
        with sqlite3.connect(destino) as conn:
            self.assertEqual(conn.execute("SELECT valor FROM precos").fetchone()[0], 125)

    def test_nao_sobrescrever_backup(self):
        criar_backup(self.conn, self.arquivo)
        with self.assertRaises(ErroBackup):
            criar_backup(self.conn, self.arquivo)

    def test_nao_restaurar_sobre_existente(self):
        criar_backup(self.conn, self.arquivo)
        (self.path / "restaurado.sqlite").write_text("manter")
        with self.assertRaises(ErroBackup):
            restaurar_backup(self.arquivo, self.path / "restaurado.sqlite")
        self.assertEqual((self.path / "restaurado.sqlite").read_text(), "manter")

    def test_sha_esperado_incorreto_falha(self):
        criar_backup(self.conn, self.arquivo)
        with self.assertRaises(ErroBackup):
            restaurar_backup(self.arquivo, self.path / "r.sqlite", sha256_esperado="f"*64)

    def test_arquivo_corrompido_nao_e_sqlite(self):
        self.arquivo.write_bytes(b"arquivo invalido")
        with self.assertRaises(ErroBackup):
            restaurar_backup(self.arquivo, self.path / "r.sqlite")

    def test_symlink_da_fonte_nao_permitido(self):
        criar_backup(self.conn, self.arquivo)
        link = self.path / "link.sqlite"
        try:
            link.symlink_to(self.arquivo)
        except (OSError, NotImplementedError):
            self.skipTest("sistema sem symlinks")
        with self.assertRaises(ErroBackup):
            restaurar_backup(link, self.path / "r.sqlite")

    def test_integridade_e_backup_sem_dependencias(self):
        criar_backup(self.conn, self.arquivo)
        with sqlite3.connect(self.arquivo) as conn:
            self.assertEqual(conn.execute("PRAGMA integrity_check").fetchone()[0], "ok")

    def test_snapshot_reflete_transacao_confirmada(self):
        self.conn.execute("UPDATE precos SET valor=140 WHERE id=1")
        self.conn.commit()
        criar_backup(self.conn, self.arquivo)
        with sqlite3.connect(self.arquivo) as conn:
            self.assertEqual(conn.execute("SELECT valor FROM precos").fetchone()[0], 140)


if __name__ == "__main__":
    unittest.main()
