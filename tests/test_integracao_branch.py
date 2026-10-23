"""E2E local Git history: divergence check must not mutate or merge branches."""
import subprocess
from pathlib import Path
import tempfile
import unittest

from nivon.integracao_branch import inspect


class TestIntegracaoBranch(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.run_git("init", "-q", "-b", "main")
        (self.root / "src.py").write_text("value=1\n", encoding="utf-8")
        self.run_git("add", "src.py")
        self.commit("base")

    def tearDown(self):
        self.tmp.cleanup()

    def run_git(self, *args):
        return subprocess.run(["git", *args], cwd=self.root,
                              capture_output=True, text=True, check=True).stdout.strip()

    def commit(self, name):
        self.run_git("-c", "user.email=ci@example.invalid",
                     "-c", "user.name=NIVON CI", "commit", "-qm", name)

    def test_branch_divergence_and_same_file(self):
        self.run_git("checkout", "-qb", "feature")
        (self.root / "src.py").write_text("value=2\n", encoding="utf-8")
        self.run_git("add", ".")
        self.commit("feature edit")
        head_before = self.run_git("rev-parse", "HEAD")
        self.run_git("checkout", "-q", "main")
        (self.root / "src.py").write_text("value=3\n", encoding="utf-8")
        self.run_git("add", ".")
        self.commit("main edit")
        self.run_git("checkout", "-q", "feature")
        report = inspect(self.root)
        self.assertEqual(report["main_commits_since_base"], 1)
        self.assertEqual(report["branch_commits_since_base"], 1)
        self.assertEqual(report["same_files_modified"], ["src.py"])
        self.assertTrue(report["needs_reconciliation"])
        self.assertEqual(report["remote_freshness"], "unknown; no git fetch performed")
        self.assertEqual(self.run_git("rev-parse", "HEAD"), head_before)
        self.assertEqual(self.run_git("status", "--porcelain"), "")

    def test_base_branch_clean(self):
        state = inspect(self.root)
        self.assertFalse(state["needs_reconciliation"])
        self.assertEqual(state["same_files_count"], 0)
        self.assertEqual(state["risk"], "none")

    def test_requires_git_repository(self):
        with tempfile.TemporaryDirectory() as outside:
            with self.assertRaises(RuntimeError):
                inspect(outside)


if __name__ == "__main__":
    unittest.main()
