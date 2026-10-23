"""CLI tree termination: real temporary processes, no Claude/Codex sessions."""
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import unittest

from nivon.processos import executar_cli


class TestProcessos(unittest.TestCase):
    def test_success_has_private_log_and_no_restart(self):
        with tempfile.TemporaryDirectory() as tmp:
            log = Path(tmp) / "session.log"
            result = executar_cli(
                [sys.executable, "-c", "print('local offline')"],
                cwd=tmp, logfile=log, env=os.environ.copy(), timeout_seconds=5)
            self.assertEqual(result.exit_code, 0)
            self.assertFalse(result.timed_out)
            self.assertTrue(result.cleanup_confirmed)
            self.assertIn("local offline", log.read_text(encoding="utf-8"))
            if os.name == "posix":
                self.assertEqual(log.stat().st_mode & 0o777, 0o600)
            with self.assertRaises(FileExistsError):
                executar_cli([sys.executable, "-c", "pass"],
                             cwd=tmp, logfile=log, env=os.environ.copy(),
                             timeout_seconds=5)

    def test_invalid_args_never_spawn(self):
        with tempfile.TemporaryDirectory() as tmp:
            log = Path(tmp) / "bad.log"
            for argv, duration in (([], 5), (["cmd"], 0), (["cmd"], 3601)):
                with self.assertRaises(ValueError):
                    executar_cli(argv, cwd=tmp, logfile=log,
                                 env=os.environ.copy(), timeout_seconds=duration)
            self.assertFalse(log.exists())

    @unittest.skipUnless(os.name == "posix", "Teste real de grupo POSIX")
    def test_timeout_kills_child_process_before_delayed_side_effect(self):
        with tempfile.TemporaryDirectory() as tmp:
            marker = Path(tmp) / "orphan-still-working.txt"
            log = Path(tmp) / "blocked.log"
            child = ("import sys,time,pathlib;"
                     "time.sleep(1.8);"
                     "pathlib.Path(sys.argv[1]).write_text('escaped')")
            parent = ("import subprocess,sys,time;"
                      "subprocess.Popen([sys.executable,'-c',sys.argv[2],sys.argv[1]]);"
                      "time.sleep(30)")
            started = time.monotonic()
            result = executar_cli(
                [sys.executable, "-c", parent, str(marker), child],
                cwd=tmp, logfile=log, env=os.environ.copy(), timeout_seconds=1)
            self.assertTrue(result.timed_out)
            self.assertLess(time.monotonic() - started, 5)
            time.sleep(1.2)
            self.assertFalse(marker.exists(), "Descendente sobreviveu ao timeout")

    @unittest.skipUnless(os.name == "posix", "Teste real de grupo POSIX")
    def test_successful_parent_cannot_leave_descendant_working(self):
        with tempfile.TemporaryDirectory() as tmp:
            marker = Path(tmp) / "orphan-success.txt"
            log = Path(tmp) / "session.log"
            child = ("import sys,time,pathlib;"
                     "time.sleep(1.0);"
                     "pathlib.Path(sys.argv[1]).write_text('escaped')")
            parent = ("import subprocess,sys;"
                      "subprocess.Popen([sys.executable,'-c',sys.argv[2],sys.argv[1]])")
            result = executar_cli(
                [sys.executable, "-c", parent, str(marker), child],
                cwd=tmp, logfile=log, env=os.environ.copy(), timeout_seconds=5)
            self.assertEqual(result.exit_code, 0)
            time.sleep(1.2)
            self.assertFalse(marker.exists(), "Descendente persistiu após sucesso da CLI")


if __name__ == "__main__":
    unittest.main()
