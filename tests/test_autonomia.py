"""Offline tests for the bounded cooperative runner. Never invoke real LLMs."""
import json
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from nivon import autonomia
from nivon.cooperacao import connect, seed, report


class TestAutonomia(unittest.TestCase):
    def test_cli_restricts_permissions_and_skips_extra_providers(self):
        task = {"id": "sample", "title": "Teste", "scope": '["src/x.py"]'}
        claude = autonomia.cli("claude", task)
        self.assertIn("--restricted", claude)
        self.assertIn("--tools", claude)
        self.assertIn("--permission-prompts", claude)
        self.assertNotIn("Bash", claude)
        self.assertNotIn("bypassPermissions", claude)
        self.assertNotIn("danger-full-access", claude)
        self.assertIn("mcp__*", claude)
        codex = autonomia.cli("codex", task)
        self.assertIn("workspace-write", codex)
        self.assertIn("never", codex)
        self.assertNotIn("danger-full-access", codex)
        self.assertNotIn("--yolo", codex)
        with self.assertRaises(ValueError):
            autonomia.cli("unknown", task)

    def test_prompt_disallows_cloud_and_unscoped_changes(self):
        text = autonomia.prompt({"id": "i1", "title": "Testar INMET",
                                 "scope": '["src/nivon/inmet_historico.py"]'})
        self.assertIn("INMET", text)
        self.assertIn("não instale dependências", text)
        self.assertIn("Arquivos permitidos", text)

    def test_worktree_status_outside_scope_blocked(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            fake = subprocess.CompletedProcess([], 0, " M src/outro.py\n", "")
            with patch.object(autonomia, "command", return_value=fake):
                with self.assertRaisesRegex(RuntimeError, "fora do escopo"):
                    autonomia.within_scope(root, ["src/permitido.py"])

    def test_worktree_symlinks_blocked(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "redirect.py").symlink_to("inexistente.py")
            fake = subprocess.CompletedProcess([], 0, "?? redirect.py\n", "")
            with patch.object(autonomia, "command", return_value=fake):
                with self.assertRaisesRegex(RuntimeError, "Symlink"):
                    autonomia.within_scope(root, ["redirect.py"])

    def test_manifest_claimed_by_distinct_agents(self):
        with tempfile.TemporaryDirectory() as tmp:
            dbpath = Path(tmp) / "queue.sqlite"
            jobs = [
                {"id": "c", "title": "C", "scope": ["src/c.py"], "preferred_agent": "claude"},
                {"id": "x", "title": "X", "scope": ["src/x.py"], "preferred_agent": "codex"},
            ]
            with connect(dbpath) as db:
                seed(db, jobs)
            with patch.object(autonomia, "preflight"), \
                 patch.object(autonomia, "default_db", return_value=dbpath), \
                 patch.object(autonomia, "HOME", Path(tmp)), \
                 patch.object(autonomia, "do_task", side_effect=lambda agent,task,**kwargs:
                              ("done", f"{agent}: local fake")):
                result = autonomia.run(max_tasks=2, minutes=2, per_task=2)
            self.assertEqual(result["counts"]["done"], 2)
            self.assertEqual({row["agent"] for row in result["executions"]},
                             {"claude", "codex"})
            with connect(dbpath) as db:
                self.assertEqual(report(db)["counts"]["running"], 0)

    def test_quota_handoff_no_infinite_loop(self):
        with tempfile.TemporaryDirectory() as tmp:
            dbpath = Path(tmp) / "queue.sqlite"
            with connect(dbpath) as db:
                seed(db, [{"id": "x", "title": "X", "scope": ["src/x.py"],
                           "preferred_agent": "claude"}])
            def fake(agent, task, **kwargs):
                return ("quota", "limite da assinatura") if agent == "claude" else ("done", "completado")
            with patch.object(autonomia, "preflight"), \
                 patch.object(autonomia, "default_db", return_value=dbpath), \
                 patch.object(autonomia, "HOME", Path(tmp)), \
                 patch.object(autonomia, "do_task", side_effect=fake):
                result = autonomia.run(max_tasks=2, minutes=2, per_task=2)
            self.assertEqual(result["counts"]["running"], 0)
            self.assertIn(result["counts"]["done"] + result["counts"]["pending"], (1,))
            self.assertLessEqual(len(result["executions"]), 2)

    def test_run_limits_and_no_llm_on_preflight(self):
        with patch.object(autonomia, "preflight", side_effect=RuntimeError("sem CLI")):
            self.assertEqual(autonomia.main(["run", "--max-tasks", "1"]), 2)


if __name__ == "__main__":
    unittest.main()
