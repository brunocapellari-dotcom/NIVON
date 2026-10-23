"""Regras de qualidade estrutural sem executar arquivos do usuário."""
from pathlib import Path
from subprocess import CompletedProcess
import tempfile
import unittest
from unittest.mock import patch

from nivon import qualidade


class TestQualidade(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        (self.root / "src").mkdir()
        (self.root / "tests").mkdir()

    def tearDown(self):
        self.temp.cleanup()

    def test_ast_scan_safe_without_code_execution(self):
        p = self.root / "src" / "sample.py"
        p.write_text("import os\nos.system('echo DO_NOT_RUN')\ndef method(): return 1\n",
                     encoding="utf-8")
        result = qualidade.syntax_scan(self.root)
        self.assertEqual(result["errors"], 0)
        self.assertEqual(result["files_checked"], 1)

    def test_syntax_fail_is_precisely_identified(self):
        (self.root / "src" / "bad.py").write_text("def invalid(:\n  pass\n", encoding="utf-8")
        result = qualidade.syntax_scan(self.root)
        self.assertEqual(result["errors"], 1)
        self.assertEqual(result["samples"][0]["file"], "src/bad.py")

    def test_ruff_absent_does_not_block_structural_scan(self):
        with patch.object(qualidade.shutil, "which", return_value=None):
            result = qualidade.report(self.root)
        self.assertTrue(result["passed"])
        self.assertEqual(result["ruff"]["status"], "not_installed")

    def test_ruff_finding_blocks_clean_claim(self):
        (self.root / "src" / "app.py").write_text("value = unknown\n", encoding="utf-8")
        message = '[{"filename": "' + str(self.root / "src" / "app.py") + '", "code": "F821", "location": {"row": 1}}]'
        with patch.object(qualidade.shutil, "which", return_value="/bin/ruff"), \
             patch.object(qualidade.subprocess, "run",
                          return_value=CompletedProcess([], 1, message, "")):
            result = qualidade.report(self.root)
        self.assertFalse(result["passed"])
        self.assertEqual(result["ruff"]["diagnostics"], 1)
        self.assertEqual(result["ruff"]["samples"][0]["file"], "src/app.py")

    def test_no_automatic_install_or_network(self):
        with patch.object(qualidade.shutil, "which", return_value=None), \
             patch.object(qualidade.subprocess, "run") as invoked:
            qualidade.report(self.root)
        invoked.assert_not_called()


if __name__ == "__main__":
    unittest.main()
