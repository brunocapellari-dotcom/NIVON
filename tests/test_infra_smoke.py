"""Ensaio de controle E2E sem rede, sem operações de produção."""
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from nivon.infra_job_ledger import abrir_ledger, resumo
from nivon.infra_smoke import executar_smoke


class TestInfraSmoke(unittest.TestCase):
    INSTANTE = "2026-10-20T11:00:00-03:00"

    def test_pipeline_efemero_sem_publicar(self):
        result = executar_smoke(instante=self.INSTANTE)
        self.assertEqual(result["estado"],"SUCCEEDED")
        self.assertTrue(result["registro_novo"])
        self.assertTrue(result["execucao_nova"])
        self.assertFalse(result["coleta_real"])
        self.assertFalse(result["publicacao"])
        self.assertFalse(result["agendamento"])
        self.assertFalse(result["backup_remoto_verificado"])
        self.assertEqual(result["eventos"],3)

    def test_sqlite_persistente_e_reexecucao_idempotente(self):
        with tempfile.TemporaryDirectory() as folder:
            os.chmod(folder,0o700)
            path=Path(folder)/"ledger.sqlite"
            a=executar_smoke(banco=path,instante=self.INSTANTE)
            b=executar_smoke(banco=path,instante=self.INSTANTE)
            self.assertTrue(a["execucao_nova"])
            self.assertFalse(b["execucao_nova"])
            self.assertFalse(b["registro_novo"])
            self.assertEqual(a["eventos"],b["eventos"])
            with abrir_ledger(path) as db:
                self.assertEqual(resumo(db)["contagens"]["SUCCEEDED"],1)

    def test_instantes_diferentes_nao_confundem_execucoes(self):
        with tempfile.TemporaryDirectory() as folder:
            os.chmod(folder,0o700)
            path=Path(folder)/"jobs.sqlite"
            executar_smoke(banco=path,instante=self.INSTANTE)
            executar_smoke(banco=path,instante="2026-10-21T11:00:00-03:00")
            with abrir_ledger(path) as db:
                self.assertEqual(resumo(db)["contagens"]["SUCCEEDED"],2)

    def test_cli_explicitamente_sintetico(self):
        root=Path(__file__).resolve().parents[1]
        env=dict(os.environ,PYTHONPATH=str(root/"src"))
        p=subprocess.run([sys.executable,"-m","nivon.infra_smoke",
                    "--instante",self.INSTANTE],cwd=root,env=env,
                    capture_output=True,text=True,timeout=15,check=False)
        self.assertEqual(p.returncode,0,p.stderr)
        res=json.loads(p.stdout)
        self.assertEqual(res["estado"],"SUCCEEDED")
        self.assertFalse(res["publicacao"])

    def test_datetime_sem_fuso_rejeitado(self):
        from nivon.infra_job_ledger import ErroJob
        with self.assertRaises(ErroJob):
            executar_smoke(instante="2026-10-20T11:00:00")


if __name__=="__main__":
    unittest.main()
