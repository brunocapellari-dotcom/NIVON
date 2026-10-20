"""Diagnóstico NIVON: alerta legível sem abrir serviços ou alterar estado."""
import copy
import hashlib
import json
import os
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from nivon.infra_health import ErroSaude, verificar_saude
from nivon.infra_preflight import carregar_inventario, InfraError
from nivon.infra_job_ledger import abrir_ledger, registrar, reservar, finalizar, resumo


class TestInfraHealth(unittest.TestCase):
    NOW = "2026-10-20T16:00:00Z"
    DUE = "2026-10-20T15:58:00Z"
    SHA = hashlib.sha256(b"fixture-infra-health").hexdigest()
    KEY = "TEST_SYNTHETIC_HEALTH_MONITOR"

    def setUp(self):
        self.inv = carregar_inventario()
        self.temp = tempfile.TemporaryDirectory()
        os.chmod(self.temp.name, 0o700)
        self.path = Path(self.temp.name) / "ledger.sqlite"

    def tearDown(self):
        self.temp.cleanup()

    def create_job(self, *, running=False, done=False, now="2026-10-20T15:59:00Z"):
        with abrir_ledger(self.path) as conn:
            registrar(conn, chave=self.KEY, vencimento=self.DUE,
                      input_sha256=self.SHA, registrado_em=self.DUE)
            if running or done:
                job = reservar(conn, chave=self.KEY, vencimento=self.DUE,
                              agora=now, lease_segundos=180)
                if done:
                    finalizar(conn, chave=self.KEY, vencimento=self.DUE,
                             agora="2026-10-20T15:59:01Z", token=job["token"],
                             sucesso=True, output_sha256=self.SHA)

    def test_sem_ledger_nao_declara_ambiente_operacional(self):
        result = verificar_saude(inventario=self.inv, agora=self.NOW)
        self.assertEqual(result["estado"], "NOT_OPERATIONAL")
        self.assertEqual(result["ledger"]["estado"], "NOT_CONFIGURED")
        self.assertIn("REMOTE_RECOVERY_NOT_VERIFIED", result["avisos"])
        self.assertIn("CLOUD_NOT_VERIFIED", result["avisos"])
        self.assertEqual(result["gates_bloqueados"], 16)
        self.assertFalse(result["envio_whatsapp"])

    def test_ledger_vazio_e_inspecionado_sem_escrever(self):
        with abrir_ledger(self.path):
            pass
        result = verificar_saude(inventario=self.inv, agora=self.NOW,
                                ledger=self.path)
        self.assertEqual(result["ledger"]["jobs"], 0)
        self.assertEqual(result["ledger"]["estado"], "SYNTHETIC_OFFLINE_ONLY")
        self.assertNotIn("JOB_LEDGER_NOT_CONFIGURED", result["avisos"])

    def test_sucesso_sintetico_nao_vira_producao(self):
        self.create_job(done=True)
        r = verificar_saude(inventario=self.inv, agora=self.NOW, ledger=self.path)
        self.assertEqual(r["ledger"]["jobs"], 1)
        self.assertTrue(r["ledger"]["ultimo_sucesso"])
        self.assertFalse(r["producao_aprovada"])
        self.assertFalse(r["coleta_real"])

    def test_expirado_e_detectado_sem_mutacao(self):
        self.create_job(running=True,now="2026-10-20T15:58:10Z")
        result = verificar_saude(inventario=self.inv, agora=self.NOW,ledger=self.path)
        self.assertEqual(result["ledger"]["leases_vencidos"],1)
        self.assertIn("EXPIRED_RUNNING_LEASES_NEED_RECONCILIATION",result["avisos"])
        with abrir_ledger(self.path) as conn:
            self.assertEqual(resumo(conn)["contagens"]["RUNNING"],1)

    def test_uncertain_exige_reconciliacao(self):
        self.create_job(running=True,now="2026-10-20T15:58:10Z")
        with abrir_ledger(self.path) as conn:
            from nivon.infra_job_ledger import reconciliar_vencidos
            self.assertEqual(reconciliar_vencidos(conn,agora=self.NOW),1)
        r = verificar_saude(inventario=self.inv, agora=self.NOW, ledger=self.path)
        self.assertEqual(r["ledger"]["incertos"],1)
        self.assertIn("UNCERTAIN_JOBS_NEED_MANUAL_RECONCILIATION",r["avisos"])

    def test_pasta_aberta_para_grupo_bloqueada(self):
        self.create_job()
        os.chmod(self.temp.name,0o755)
        with self.assertRaises(ErroSaude):
            verificar_saude(inventario=self.inv, agora=self.NOW, ledger=self.path)

    def test_arquivo_nao_e_criado_automaticamente(self):
        self.assertFalse(self.path.exists())
        with self.assertRaises(ErroSaude):
            verificar_saude(inventario=self.inv, agora=self.NOW, ledger=self.path)
        self.assertFalse(self.path.exists())

    def test_link_simbolico_bloqueado(self):
        self.create_job()
        symlink = Path(self.temp.name)/"link.sqlite"
        symlink.symlink_to(self.path)
        with self.assertRaises(ErroSaude):
            verificar_saude(inventario=self.inv, agora=self.NOW,ledger=symlink)

    def test_banco_sem_schema_bloqueado(self):
        with sqlite3.connect(self.path) as conn:
            conn.execute("CREATE TABLE tab(x INTEGER)")
        with self.assertRaises(ErroSaude):
            verificar_saude(inventario=self.inv,agora=self.NOW,ledger=self.path)

    def test_manipular_gate_e_rejeitado(self):
        inv = copy.deepcopy(self.inv)
        inv["release_gates"]["BACKUP_RESTORE"] = True
        with self.assertRaises(InfraError):
            verificar_saude(inventario=inv, agora=self.NOW)

    def test_exige_fuso(self):
        with self.assertRaises(ValueError):
            verificar_saude(inventario=self.inv,agora="2026-10-20T16:00:00")

    def test_cli_passivo_e_gate(self):
        root = Path(__file__).resolve().parents[1]
        env=dict(os.environ,PYTHONPATH=str(root/"src"))
        cmd=[sys.executable,"-m","nivon.infra_health","--agora",self.NOW]
        out=subprocess.run(cmd,cwd=root,env=env,timeout=20,
                           capture_output=True,text=True,check=False)
        self.assertEqual(out.returncode,0,out.stderr)
        self.assertEqual(json.loads(out.stdout)["estado"],"NOT_OPERATIONAL")
        check=subprocess.run(cmd+["--require-operational"],cwd=root,env=env,
                             timeout=20,capture_output=True,text=True,check=False)
        self.assertEqual(check.returncode,3)
        self.assertFalse(self.path.exists())


if __name__=="__main__":
    unittest.main()
