"""Tests for offline cooperative ledger and token-efficient log summaries."""
import tempfile
from pathlib import Path
import unittest

from nivon.cooperacao import change, claim, clean_scope, connect, overlap, report, seed
from nivon.token_guard import summarize


class TestLedger(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.db = connect(Path(self.temp.name) / "coop.sqlite")

    def tearDown(self):
        self.db.close()
        self.temp.cleanup()

    def test_parallel_distinct_tasks_and_idempotent_seed(self):
        jobs = [
            {"id": "one", "title": "INMET", "scope": ["src/nivon/inmet_historico.py"],
             "preferred_agent": "claude", "priority": 1},
            {"id": "two", "title": "CPTEC", "scope": ["src/nivon/cptec_previsao_brasilapi.py"],
             "preferred_agent": "codex", "priority": 1},
        ]
        self.assertEqual(seed(self.db, jobs), 2)
        self.assertEqual(seed(self.db, jobs), 0)
        self.assertEqual(claim(self.db, "claude")["id"], "one")
        self.assertEqual(claim(self.db, "codex")["id"], "two")
        self.assertIsNone(claim(self.db, "claude"))

    def test_no_overlapping_writers(self):
        jobs = [
            {"id": "one", "title": "A", "scope": ["src/nivon"], "preferred_agent": "any"},
            {"id": "two", "title": "B", "scope": ["src/nivon/ana.py"], "preferred_agent": "any"},
        ]
        seed(self.db, jobs)
        self.assertTrue(overlap(["src/nivon"], ["src/nivon/ana.py"]))
        self.assertEqual(claim(self.db, "codex")["id"], "one")
        self.assertIsNone(claim(self.db, "claude"))

    def test_handoff_requires_checkpoint_and_ownership(self):
        seed(self.db, [{"id": "x", "title": "X", "scope": ["src/x.py"], "preferred_agent": "any"}])
        claim(self.db, "claude")
        with self.assertRaises(ValueError):
            change(self.db, "x", "codex", "done")
        with self.assertRaises(ValueError):
            change(self.db, "x", "claude", "handoff", "")
        change(self.db, "x", "claude", "handoff", "Branch x, SHA abc, teste falhou")
        self.assertEqual(claim(self.db, "codex")["id"], "x")
        change(self.db, "x", "codex", "done", "SHA def, testes OK", tokens_in=100, tokens_out=20)
        self.assertEqual(report(self.db)["tokens_reported"], {"input": 100, "output": 20})

    def test_provider_handoff_preserves_checkpoint(self):
        seed(self.db, [{"id": "x", "title": "X", "scope": ["src/x.py"],
                        "preferred_agent": "claude"}])
        self.assertEqual(claim(self.db, "claude")["id"], "x")
        change(self.db, "x", "claude", "handoff", "branch x, SHA abc, passos para continuar",
               next_agent="codex")
        self.assertEqual(claim(self.db, "codex")["id"], "x")
        with self.assertRaises(ValueError):
            change(self.db, "x", "codex", "done", next_agent="claude")


    def test_expired_task_not_reclaimed_automatically(self):
        seed(self.db, [{"id": "x", "title": "X", "scope": ["src/x.py"], "preferred_agent": "any"}])
        claim(self.db, "claude")
        self.db.execute("UPDATE tasks SET lease_until='2020-01-01T00:00:00+00:00'")
        self.db.commit()
        self.assertEqual(report(self.db)["stale_needs_review"], ["x"])
        self.assertIsNone(claim(self.db, "codex"))

    def test_reject_unsafe_scope_and_duplicate_ids(self):
        for path in ("../private", "/etc/passwd", "~/secret", "src/../../bad"):
            with self.assertRaises(ValueError):
                clean_scope([path])
        with self.assertRaises(ValueError):
            seed(self.db, [
                {"id": "same", "title": "A", "scope": ["src/a"]},
                {"id": "same", "title": "B", "scope": ["src/b"]},
            ])
        self.assertEqual(report(self.db)["counts"]["pending"], 0)

    def test_invalid_claim_or_completion(self):
        with self.assertRaises(ValueError):
            claim(self.db, "unknown")
        with self.assertRaises(ValueError):
            change(self.db, "absent", "claude", "done")


class TestLogGuard(unittest.TestCase):
    def test_failure_preserved_and_secrets_masked(self):
        raw = "start\n" + "OK\n"*80 + "ERROR token=verysecret\nTraceback\nBearer someverylongtoken123\n"
        result = summarize(raw, 1000)
        self.assertIn("ERROR", result)
        self.assertIn("[REDACTED]", result)
        self.assertNotIn("verysecret", result)
        self.assertLess(len(result), len(raw))

    def test_short_successful_log(self):
        self.assertIn("OK", summarize("start\nOK\n"))


if __name__ == "__main__":
    unittest.main()
