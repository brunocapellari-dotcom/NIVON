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
        self.assertIn("--safe-mode", claude)
        self.assertNotIn("--bare", claude)
        self.assertIn("--no-session-persistence", claude)
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
            with patch.object(autonomia, "may_begin", return_value=True), \
                 patch.object(autonomia, "preflight"), \
                 patch.object(autonomia, "default_db", return_value=dbpath), \
                 patch.object(autonomia, "HOME", Path(tmp)), \
                 patch.object(autonomia, "refresh_plan", return_value={"added": 0}), \
                 patch.object(autonomia, "prepare_integration", return_value=Path(tmp)/"integration"), \
                 patch.object(autonomia, "get_issues", return_value=([], None)), \
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
            with patch.object(autonomia, "may_begin", return_value=True), \
                 patch.object(autonomia, "preflight"), \
                 patch.object(autonomia, "default_db", return_value=dbpath), \
                 patch.object(autonomia, "HOME", Path(tmp)), \
                 patch.object(autonomia, "refresh_plan", return_value={"added": 0}), \
                 patch.object(autonomia, "prepare_integration", return_value=Path(tmp)/"integration"), \
                 patch.object(autonomia, "get_issues", return_value=([], None)), \
                 patch.object(autonomia, "do_task", side_effect=fake):
                result = autonomia.run(max_tasks=2, minutes=2, per_task=2)
            self.assertEqual(result["counts"]["running"], 0)
            self.assertIn(result["counts"]["done"] + result["counts"]["pending"], (1,))
            self.assertLessEqual(len(result["executions"]), 2)

    def test_cli_usage_parsers_are_best_effort(self):
        with tempfile.TemporaryDirectory() as tmp:
            logfile = Path(tmp) / "usage.log"
            logfile.write_text(json.dumps({"usage": {"input_tokens": 220, "output_tokens": 40}}),
                               encoding="utf-8")
            self.assertEqual(autonomia.usage_from_log(logfile), (220, 40))
            logfile.write_text(
                '{"type":"thread.started"}\n'
                '{"type":"turn.completed","usage":{"input_tokens":330,"output_tokens":44}}\n',
                encoding="utf-8"
            )
            self.assertEqual(autonomia.usage_from_log(logfile), (330, 44))
            logfile.write_text("texto sem métricas", encoding="utf-8")
            self.assertEqual(autonomia.usage_from_log(logfile), (None, None))

    def test_prepare_integration_fail_closed_on_unexpected_branch(self):
        with tempfile.TemporaryDirectory() as tmp:
            location = Path(tmp) / "integration"
            location.mkdir()
            with patch.object(autonomia, "HOME", Path(tmp)), \
                 patch.object(autonomia, "command",
                              return_value=subprocess.CompletedProcess([], 0, "main\n", "")):
                with self.assertRaisesRegex(RuntimeError, "inválida"):
                    autonomia.prepare_integration()

    def test_local_integration_cherry_pick_and_offline_gate(self):
        commands = []
        rev_count = 0
        def fake(args, cwd=autonomia.ROOT, **kwargs):
            nonlocal rev_count
            commands.append(args)
            if args[:3] == ["git", "rev-parse", "HEAD"]:
                rev_count += 1
                return subprocess.CompletedProcess(args, 0, "before\n" if rev_count == 1 else "after\n", "")
            return subprocess.CompletedProcess(args, 0, "", "")
        with patch.object(autonomia, "prepare_integration", return_value=Path("/tmp/nivon-integration")), \
             patch.object(autonomia, "command", side_effect=fake):
            approved, note = autonomia.integrate_local("deadbeef", "python:3.11-slim")
        self.assertTrue(approved)
        self.assertIn("after", note)
        self.assertTrue(any("cherry-pick" in cmd for cmd in commands))
        self.assertTrue(any("--network" in cmd and "none" in cmd for cmd in commands))
        self.assertFalse(any("--force" in cmd or "--push" in cmd for cmd in commands))

    def test_conflicting_cherry_pick_preserves_feature_branch(self):
        commands = []
        def fake(args, cwd=autonomia.ROOT, **kwargs):
            commands.append(args)
            if "cherry-pick" in args and "--abort" not in args:
                return subprocess.CompletedProcess(args, 1, "", "conflict")
            return subprocess.CompletedProcess(args, 0, "before\n" if "rev-parse" in args else "", "")
        with patch.object(autonomia, "prepare_integration", return_value=Path("/tmp/nivon-integration")), \
             patch.object(autonomia, "command", side_effect=fake):
            approved, reason = autonomia.integrate_local("deadbeef", "python:3.11-slim")
        self.assertFalse(approved)
        self.assertIn("Conflito", reason)
        self.assertTrue(any("--abort" in cmd for cmd in commands))
        self.assertFalse(any("reset" in cmd for cmd in commands))

    def test_supervisor_lock_blocks_parallel_processes(self):
        with tempfile.TemporaryDirectory() as tmp:
            with patch.object(autonomia, "HOME", Path(tmp)):
                with autonomia.supervisor_lock():
                    with self.assertRaises(RuntimeError):
                        with autonomia.supervisor_lock():
                            pass
                self.assertFalse((Path(tmp) / "supervisor.pid").exists())

    def test_preflight_rejects_billed_or_missing_subscription(self):
        from unittest.mock import MagicMock
        with patch.object(autonomia.shutil, "which", return_value="/usr/bin/tool"), \
             patch.object(autonomia, "check_tools",
                          return_value={"ready_for_pilot": False}), \
             patch.object(autonomia, "command") as cmd:
            with self.assertRaisesRegex(RuntimeError, "Doctor rejeitou"):
                autonomia.preflight()
            cmd.assert_not_called()

    def test_run_limits_and_no_llm_on_preflight(self):
        with patch.object(autonomia, "preflight", side_effect=RuntimeError("sem CLI")):
            self.assertEqual(autonomia.main(["run", "--max-tasks", "1"]), 2)


if __name__ == "__main__":
    unittest.main()
