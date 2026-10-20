"""Regressões fail-closed do ensaio Restic. E2E real roda apenas com Restic instalado."""
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from nivon.infra_restic_drill import (
    ErroRestic, _comando, _credenciais_temporarias, _guardas, executar_drill,
)

ROOT = Path(__file__).resolve().parents[1]


class TestResticFailClosed(unittest.TestCase):
    def test_cli_default_inerte(self):
        env = dict(os.environ, PYTHONPATH=str(ROOT / "src"))
        p = subprocess.run([sys.executable, "-m", "nivon.infra_restic_drill"],
                           cwd=ROOT, env=env, capture_output=True, text=True,
                           check=False, timeout=20)
        self.assertEqual(p.returncode, 0, p.stderr)
        self.assertEqual(json.loads(p.stdout)["estado"], "OFF_BY_DEFAULT")

    def test_flags_operacionais_bloqueadas(self):
        for field in ("NIVON_RUNTIME_ENABLED", "NIVON_COLLECTORS_ENABLED",
                      "NIVON_PUBLICATION_ENABLED", "NIVON_BACKUP_ENABLED"):
            with self.subTest(field=field), self.assertRaises(ErroRestic):
                _guardas({field: "true"})
        _guardas({})

    def test_binario_restic_necessario(self):
        with patch("nivon.infra_restic_drill.shutil.which", return_value=None):
            with self.assertRaisesRegex(ErroRestic, "não instalado"):
                executar_drill(ambiente={})

    def test_comandos_nao_permitidos_bloqueados(self):
        with tempfile.TemporaryDirectory() as tmp:
            for args in (["forget", "--prune"], ["unlock"], []):
                with self.subTest(args=args), self.assertRaises(ErroRestic):
                    _comando("/usr/bin/restic", args, ambiente={}, pasta=Path(tmp))

    def test_subprocesso_sem_shell_ou_credenciais_herdadas(self):
        class Result:
            returncode, stdout, stderr = 0, "ok", ""
        with tempfile.TemporaryDirectory() as tmp:
            with patch("nivon.infra_restic_drill.subprocess.run", return_value=Result()) as call:
                self.assertEqual(_comando("restic", ["check"],
                                          ambiente={"RESTIC_REPOSITORY": tmp},
                                          pasta=Path(tmp)), "ok")
                self.assertEqual(call.call_args.args[0],
                                 ["restic", "--no-cache", "check"])
                self.assertNotIn("shell", call.call_args.kwargs)
                self.assertEqual(call.call_args.kwargs["env"],
                                 {"RESTIC_REPOSITORY": tmp})

    def test_erro_nao_expoe_saida_de_ferramenta(self):
        class Result:
            returncode, stdout, stderr = 4, "TOKEN_INTERNO", "SEGREDO_INTERNO"
        with tempfile.TemporaryDirectory() as tmp:
            with patch("nivon.infra_restic_drill.subprocess.run", return_value=Result()):
                with self.assertRaises(ErroRestic) as caught:
                    _comando("restic", ["backup", "."], ambiente={}, pasta=Path(tmp))
                self.assertNotIn("INTERNO", str(caught.exception))

    def test_arquivo_de_senha_privado_e_sem_tokens_cloud(self):
        with tempfile.TemporaryDirectory() as tmp:
            with patch.dict(os.environ, {"OCI_PRIVATE_KEY": "NEVER_LEAK",
                                         "GH_TOKEN": "NEVER_LEAK"}):
                repo, env = _credenciais_temporarias(Path(tmp))
            pw = Path(env["RESTIC_PASSWORD_FILE"])
            self.assertTrue(pw.is_file())
            self.assertEqual(pw.stat().st_mode & 0o077, 0)
            self.assertEqual(pw.parent.stat().st_mode & 0o077, 0)
            self.assertEqual(str(repo), env["RESTIC_REPOSITORY"])
            self.assertNotIn("OCI_PRIVATE_KEY", env)
            self.assertNotIn("GH_TOKEN", env)

    def test_cli_flag_real_recusada_antes_do_drill(self):
        env = dict(os.environ, PYTHONPATH=str(ROOT / "src"), NIVON_BACKUP_ENABLED="true")
        p = subprocess.run([sys.executable, "-m", "nivon.infra_restic_drill",
                            "--synthetic-drill"], cwd=ROOT, env=env, timeout=20,
                           capture_output=True, text=True, check=False)
        self.assertEqual(p.returncode, 3)
        self.assertEqual(json.loads(p.stdout)["estado"], "BLOCKED")

    @unittest.skipUnless(shutil.which("restic"), "Restic ausente no host")
    def test_e2e_snapshot_cifrado_local_e_restore(self):
        r = executar_drill(ambiente={})
        self.assertEqual(r["estado"], "RESTIC_LOCAL_ENCRYPTED_SYNTHETIC_RESTORE_OK")
        self.assertEqual(r["snapshot_count"], 1)
        self.assertEqual(r["tables_verified"], 1)
        self.assertFalse(r["remote_backup_verified"])
        self.assertFalse(r["cloud_credentials_used"])


if __name__ == "__main__":
    unittest.main()
