"""Regressão de integração: consentimento, reserva, WAL e restauração.

Simula só SQLite local, HMACs fictícios e remetente sem HTTP. Verifica que
um banco restaurado mantém bloqueio de segunda tentativa (at-most-once).
"""
from __future__ import annotations

import sqlite3
import tempfile
import unittest
from pathlib import Path

from nivon.backup_sqlite import criar_backup, restaurar_backup, ErroBackup
from nivon.outbox_briefing import abrir_outbox, reservar_para_entrega
from nivon.outbox_whatsapp import consultar_envio, despachar_registrado, ErroOutbox
from nivon.outbox_unificada import ErroControleEnvio
from test_integracao_outbox_unificada import (
    evento_consentimento, modelo, agendar, enviar,
)


class TestIntegracaoOutboxBackupWAL(unittest.TestCase):
    def test_backup_restore_preserva_consentimento_e_impede_reenvio(self):
        with tempfile.TemporaryDirectory(prefix="nivon-outbox-backup-") as tmp:
            base = Path(tmp)
            original = base / "outbox.sqlite"
            backup = base / "snapshot.sqlite"
            restaurado = base / "restaurado.sqlite"
            item = modelo()
            enviado = []
            db = abrir_outbox(original)
            try:
                evento_consentimento(db)
                from nivon.outbox_whatsapp import registrar_edicao
                from test_integracao_outbox_unificada import DATE, RECIPIENT_SECRET
                registrar_edicao(db, item, edicao=DATE,
                                chave_destinatario=RECIPIENT_SECRET)
                r = enviar(db, item, enviado)
                self.assertEqual(r["estado"], "ACEITO_PROVEDOR")
                self.assertEqual(enviado, [True])
                info = criar_backup(db, backup)
                self.assertEqual(info["integridade"], "OK")
            finally:
                db.close()

            restore = restaurar_backup(
                backup, restaurado, sha256_esperado=info["sha256"],
            )
            self.assertEqual(restore["integridade"], "OK")
            verificado = abrir_outbox(restaurado)
            try:
                self.assertEqual(
                    consultar_envio(verificado, item["idempotency_key"])["estado"],
                    "ACEITO_PROVEDOR",
                )
                # Nenhum novo POST mesmo com repetição da mesma edição.
                chamadas = []
                with self.assertRaises(ErroOutbox):
                    enviar(verificado, item, chamadas)
                self.assertEqual(chamadas, [])
                # Outra outbox para o mesmo destinatário/dia também deve
                # respeitar a reserva canônica persistida e restaurada.
                legacy = agendar(verificado)
                with self.assertRaises(ErroControleEnvio):
                    reservar_para_entrega(verificado, id=legacy["id"])
                self.assertEqual(verificado.execute(
                    "SELECT COUNT(*) FROM nivon_reservas_canonicas"
                ).fetchone()[0], 1)
                self.assertEqual(verificado.execute(
                    "PRAGMA integrity_check"
                ).fetchone()[0], "ok")
            finally:
                verificado.close()

    def test_backup_recusa_transacao_aberta_sem_criar_arquivo(self):
        with tempfile.TemporaryDirectory(prefix="nivon-wal-open-") as tmp:
            root = Path(tmp)
            db = abrir_outbox(root / "original.sqlite")
            try:
                db.execute("BEGIN IMMEDIATE")
                with self.assertRaisesRegex(ErroBackup, "transação aberta"):
                    criar_backup(db, root / "backup.sqlite")
                self.assertFalse((root / "backup.sqlite").exists())
            finally:
                db.rollback()
                db.close()


if __name__ == "__main__":
    unittest.main()
