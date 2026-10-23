"""Indicadores NIVON: nunca inventar ganho de tokens."""
import tempfile
from pathlib import Path
import unittest

from nivon.cooperacao import change, claim, connect, report, seed
from nivon.indicadores_engenharia import summarize_metrics


class TestIndicadoresEngenharia(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db = connect(Path(self.tmp.name) / "history.db")

    def tearDown(self):
        self.db.close()
        self.tmp.cleanup()

    def prepare(self, task_id, preferred_agent="claude"):
        seed(self.db, [{
            "id": task_id, "title": "Melhoria", "scope": [f"src/nivon/{task_id}.py"],
            "preferred_agent": preferred_agent
        }])

    def test_no_token_data_never_yields_productivity(self):
        self.prepare("unreported")
        claim(self.db, "claude")
        change(self.db, "unreported", "claude", "done", "successful tests")
        result = summarize_metrics(report(self.db))
        self.assertIsNone(result["groups"]["total"]["completed_per_100k_tokens"])
        self.assertEqual(result["groups"]["total"]["missing_usage_attempts"], 1)

    def test_handoff_cost_is_counted_even_if_second_agent_finishes(self):
        self.prepare("transfer")
        claim(self.db, "claude")
        change(self.db, "transfer", "claude", "handoff", "checkpoint",
               tokens_in=1000, tokens_out=100, tokens_cached=600,
               next_agent="codex")
        claim(self.db, "codex")
        change(self.db, "transfer", "codex", "done", "tests",
               tokens_in=300, tokens_out=100, tokens_cached=200)
        value = summarize_metrics(report(self.db))
        self.assertEqual(value["groups"]["total"]["completed"], 1)
        self.assertEqual(value["groups"]["total"]["attempts"], 2)
        self.assertEqual(value["groups"]["total"]["input_tokens_observed"], 1300)
        self.assertEqual(value["groups"]["total"]["output_tokens_observed"], 200)
        self.assertEqual(value["groups"]["total"]["cached_input_tokens_observed"], 800)
        self.assertAlmostEqual(value["groups"]["total"]["completed_per_100k_tokens"],
                               round(100_000 / 1500, 4))
        self.assertEqual(value["groups"]["claude"]["completed"], 0)
        self.assertEqual(value["groups"]["codex"]["completed"], 1)

    def test_partial_missing_does_not_publish_ratio(self):
        for name in ("one", "two"):
            self.prepare(name)
            claim(self.db, "claude")
            if name == "one":
                change(self.db, name, "claude", "done", "done", tokens_in=200,
                       tokens_out=40)
            else:
                change(self.db, name, "claude", "done", "done")
        data = summarize_metrics(report(self.db))
        self.assertIsNone(data["groups"]["total"]["completed_per_100k_tokens"])
        self.assertIsNone(data["groups"]["total"]["cached_input_tokens_observed"])
        self.assertEqual(data["groups"]["total"]["comparability"], "incomplete")

    def test_empty_history(self):
        data = summarize_metrics(report(self.db))
        self.assertEqual(data["groups"]["total"]["comparability"], "no_attempts")
        self.assertIsNone(data["groups"]["total"]["completed_per_100k_tokens"])


if __name__ == "__main__":
    unittest.main()
