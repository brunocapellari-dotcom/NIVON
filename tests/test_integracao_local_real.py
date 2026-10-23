"""E2E Git local: integração real em worktree, sem Claude, Codex ou Docker real.

O teste invoca git init/worktree/commit/cherry-pick dentro de um diretório
temporário. Apenas a chamada Docker é simulada: nenhum modelo é acionado.
"""
import subprocess
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from nivon import autonomia


class TestIntegracaoReal(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.base = Path(self.temp.name)
        self.repo = self.base / "source"
        self.integration = self.base / "integration"
        self.feature = self.base / "feature"
        self.repo.mkdir()
        self.git(self.repo, "init", "-q", "-b", "main")
        self.git(self.repo, "config", "user.email", "nivon-tests@example.invalid")
        self.git(self.repo, "config", "user.name", "NIVON Tests")
        (self.repo / "code.py").write_text("value = 'base'\n", encoding="utf-8")
        self.git(self.repo, "add", "code.py")
        self.git(self.repo, "commit", "-qm", "initial")
        self.git(self.repo, "worktree", "add", "-qb", "autonomo/integracao",
                 str(self.integration), "HEAD")
        self.git(self.repo, "worktree", "add", "-qb", "autonomo/change",
                 str(self.feature), "HEAD")
        (self.feature / "code.py").write_text("value = 'updated'\n", encoding="utf-8")
        self.git(self.feature, "add", "code.py")
        self.git(self.feature, "commit", "-qm", "feature change")
        self.feature_sha = self.git(self.feature, "rev-parse", "HEAD")
        self.integration_before = self.git(self.integration, "rev-parse", "HEAD")
        self.main_before = self.git(self.repo, "rev-parse", "HEAD")

    def tearDown(self):
        self.temp.cleanup()

    @staticmethod
    def git(cwd, *args):
        return subprocess.run(["git", *args], cwd=str(cwd), check=True,
                              capture_output=True, text=True).stdout.strip()

    def simulated_command(self, fail_docker=False):
        original = autonomia.command

        def call(args, cwd=autonomia.ROOT, **kwargs):
            if args and args[0] == "docker":
                return subprocess.CompletedProcess(args, 1 if fail_docker else 0, "", "")
            return original(args, cwd=cwd, **kwargs)
        return call

    def test_cherry_pick_actually_integrates_only_local_branch(self):
        with patch.object(autonomia, "prepare_integration", return_value=self.integration), \
             patch.object(autonomia, "command", side_effect=self.simulated_command()):
            done, note = autonomia.integrate_local(self.feature_sha, "python:3.11-slim")
        self.assertTrue(done, note)
        self.assertIn("testes offline OK", note)
        self.assertEqual((self.integration / "code.py").read_text(), "value = 'updated'\n")
        self.assertNotEqual(self.git(self.integration, "rev-parse", "HEAD"),
                            self.integration_before)
        self.assertEqual(self.git(self.repo, "rev-parse", "main"), self.main_before)
        self.assertEqual((self.repo / "code.py").read_text(), "value = 'base'\n")
        self.assertEqual(self.git(self.integration, "status", "--porcelain"), "")

    def test_failure_restores_only_dedicated_integration_branch(self):
        with patch.object(autonomia, "prepare_integration", return_value=self.integration), \
             patch.object(autonomia, "command", side_effect=self.simulated_command(fail_docker=True)):
            done, note = autonomia.integrate_local(self.feature_sha, "python:3.11-slim")
        self.assertFalse(done)
        self.assertIn("Regressão", note)
        self.assertEqual(self.git(self.integration, "rev-parse", "HEAD"),
                         self.integration_before)
        self.assertEqual((self.integration / "code.py").read_text(), "value = 'base'\n")
        self.assertEqual(self.git(self.feature, "rev-parse", "HEAD"), self.feature_sha)
        self.assertEqual(self.git(self.repo, "rev-parse", "main"), self.main_before)
        self.assertEqual(self.git(self.integration, "status", "--porcelain"), "")


if __name__ == "__main__":
    unittest.main()
