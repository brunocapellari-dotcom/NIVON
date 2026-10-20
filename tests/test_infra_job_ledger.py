"""Ledger de jobs: E2E SQLite local, sem operação de fonte real."""
import hashlib
import os
import sqlite3
import tempfile
import unittest
from pathlib import Path

from nivon.infra_job_ledger import (
    ErroJob, abrir_ledger, registrar, reservar, finalizar,
    reconciliar_vencidos, resumo,
)
from nivon.backup_sqlite import criar_backup, restaurar_backup


class TestJobLedger(unittest.TestCase):
    KEY = "TEST_SYNTHETIC_CI_AUDIT"
    DUE = "2026-10-20T08:00:00-04:00"
    EARLY = "2026-10-20T07:59:59-04:00"
    NOW = "2026-10-20T08:01:00-04:00"
    SHA = hashlib.sha256(b"somente-fixture").hexdigest()

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        os.chmod(self.tmp.name, 0o700)
        self.path = Path(self.tmp.name) / "jobs.sqlite"
        self.db = abrir_ledger(self.path)

    def tearDown(self):
        self.db.close()
        self.tmp.cleanup()

    def _register(self, sha=None):
        return registrar(self.db, chave=self.KEY, vencimento=self.DUE,
                        input_sha256=sha or self.SHA, registrado_em=self.EARLY)

    def _reserve(self, now=None, db=None):
        return reservar(db or self.db, chave=self.KEY, vencimento=self.DUE,
                       agora=now or self.NOW, lease_segundos=30)

    def test_idempotencia_sem_evento_extra(self):
        self.assertTrue(self._register()["novo"])
        self.assertFalse(self._register()["novo"])
        self.assertEqual(self.db.execute("SELECT COUNT(*) FROM nivon_job_event").fetchone()[0], 1)

    def test_recusa_mesmo_job_com_input_diferente(self):
        self._register()
        with self.assertRaises(ErroJob):
            self._register(hashlib.sha256(b"alterado").hexdigest())

    def test_nao_aceita_dataset_real_nem_chave_arbitraria(self):
        with self.assertRaises(ErroJob):
            registrar(self.db, chave="CONAB_SAFRA", vencimento=self.DUE,
                     input_sha256=self.SHA, registrado_em=self.NOW)
        with self.assertRaises(ErroJob):
            registrar(self.db, chave="TEST_SYNTHETIC_BAD;DROP TABLE x",
                     vencimento=self.DUE,input_sha256=self.SHA,registrado_em=self.NOW)

    def test_sem_vencimento_nao_executa(self):
        self._register()
        with self.assertRaises(ErroJob):
            self._reserve(self.EARLY)
        self.assertEqual(resumo(self.db)["contagens"]["READY"], 1)

    def test_dupla_reserva_mesma_transacao_impossivel(self):
        self._register()
        run1 = self._reserve()
        self.assertTrue(run1["reservado"])
        run2 = self._reserve()
        self.assertEqual(run2, {"reservado":False,"estado":"RUNNING"})
        self.assertEqual(self.db.execute("SELECT attempts FROM nivon_job").fetchone()[0], 1)

    def test_duas_conexoes_mesmo_banco_nao_duplicam(self):
        self._register()
        with abrir_ledger(self.path) as second:
            first = self._reserve()
            second_res = self._reserve(db=second)
            self.assertTrue(first["reservado"])
            self.assertFalse(second_res["reservado"])

    def test_reabre_e_persiste_historico(self):
        self._register()
        self.db.close()
        self.db = abrir_ledger(self.path)
        self.assertEqual(resumo(self.db)["contagens"]["READY"], 1)
        self.assertTrue(self._reserve()["reservado"])

    def test_finaliza_sucesso_sem_publicar(self):
        self._register()
        task = self._reserve()
        result = finalizar(self.db,chave=self.KEY,vencimento=self.DUE,
            token=task["token"],agora="2026-10-20T08:01:15-04:00",
            sucesso=True,output_sha256=self.SHA)
        self.assertEqual(result,{"estado":"SUCCEEDED","publicar":False})
        self.assertEqual(self._reserve()["estado"],"SUCCEEDED")
        self.assertEqual(resumo(self.db)["contagens"]["SUCCEEDED"], 1)

    def test_token_incorreto_nega_finalizacao(self):
        self._register()
        task = self._reserve()
        with self.assertRaises(ErroJob):
            finalizar(self.db,chave=self.KEY,vencimento=self.DUE,
                token="0"*48,agora="2026-10-20T08:01:10-04:00",
                sucesso=True,output_sha256=self.SHA)
        self.assertEqual(resumo(self.db)["contagens"]["RUNNING"], 1)

    def test_lease_expirado_vira_incerto_nao_retry(self):
        self._register()
        self._reserve()
        changed = reconciliar_vencidos(self.db, agora="2026-10-20T08:01:31-04:00")
        self.assertEqual(changed, 1)
        self.assertEqual(reconciliar_vencidos(self.db, agora="2026-10-20T08:01:40-04:00"),0)
        self.assertEqual(self._reserve(now="2026-10-20T08:01:50-04:00")["estado"],"UNCERTAIN")
        self.assertEqual(self.db.execute("SELECT attempts FROM nivon_job").fetchone()[0],1)

    def test_nova_reserva_com_expirado_nunca_refaz(self):
        self._register()
        self._reserve()
        r = self._reserve(now="2026-10-20T08:01:31-04:00")
        self.assertFalse(r["reservado"])
        self.assertEqual(r["estado"],"UNCERTAIN")

    def test_finalizacao_tardia_nao_promove_sucesso(self):
        self._register()
        token = self._reserve()["token"]
        r = finalizar(self.db,chave=self.KEY,vencimento=self.DUE,token=token,
            agora="2026-10-20T08:02:00-04:00",sucesso=True,output_sha256=self.SHA)
        self.assertEqual(r,{"estado":"UNCERTAIN","publicar":False})

    def test_failed_nao_e_reexecutado(self):
        self._register()
        token = self._reserve()["token"]
        out = finalizar(self.db,chave=self.KEY,vencimento=self.DUE,token=token,
            agora="2026-10-20T08:01:15-04:00",sucesso=False)
        self.assertEqual(out["estado"],"FAILED")
        self.assertFalse(self._reserve()["reservado"])

    def test_rejeita_fuso_ausente_e_lease_excessivo(self):
        with self.assertRaises(ErroJob):
            registrar(self.db,chave=self.KEY,vencimento="2026-10-20T08:00:00",
                    input_sha256=self.SHA,registrado_em=self.NOW)
        self._register()
        with self.assertRaises(ErroJob):
            reservar(self.db,chave=self.KEY,vencimento=self.DUE,
                     agora=self.NOW,lease_segundos=3601)

    def test_arquivo_privado_e_permisoes(self):
        self.assertEqual(self.path.stat().st_mode & 0o077,0)
        with tempfile.TemporaryDirectory() as d:
            os.chmod(d,0o755)
            with self.assertRaises(ErroJob):
                abrir_ledger(Path(d)/"inseguro.sqlite")

    def test_backup_restauracao_independente(self):
        self._register()
        backup = Path(self.tmp.name)/"copia.sqlite"
        proof = criar_backup(self.db,backup)
        self.assertEqual(proof["integridade"],"OK")
        target = Path(self.tmp.name)/"restaurado.sqlite"
        result = restaurar_backup(backup,target,sha256_esperado=proof["sha256"])
        self.assertEqual(result["integridade"],"OK")
        with sqlite3.connect(target) as recovered:
            self.assertEqual(recovered.execute("SELECT COUNT(*) FROM nivon_job").fetchone()[0],1)


if __name__=="__main__":
    unittest.main()
