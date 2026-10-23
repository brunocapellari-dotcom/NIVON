"""Painel Dueto: visualização privada, sem serviços ou chamadas aos agentes."""
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from nivon.cooperacao import change, claim, connect, report, seed
from nivon.dueto_painel import summary, render_html, write_private, main


class TestPainelDueto(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.database = self.root / "dueto.sqlite"
        self.db = connect(self.database)
        self.night = {
            "timezone": "America/Cuiaba", "window": "20:00-06:00",
            "active": False, "may_begin_task": False,
            "next_open": "2026-10-23T20:00:00-04:00",
            "current_or_next_close": "2026-10-24T06:00:00-04:00"
        }

    def tearDown(self):
        self.db.close()
        self.temp.cleanup()

    def test_summary_contains_two_peer_programmers_not_private_notes(self):
        seed(self.db, [
            {"id": "foo", "title": "Implementar conector ANTT",
             "scope": ["src/nivon/foo.py"], "preferred_agent": "claude"},
            {"id": "bar", "title": "Implementar série ANTAQ",
             "scope": ["src/nivon/bar.py"], "preferred_agent": "codex"},
        ])
        claim(self.db, "claude")
        change(self.db, "foo", "claude", "done", "password=DO_NOT_PUBLISH",
               tokens_in=1000, tokens_out=100)
        claim(self.db, "codex")
        payload = summary(report(self.db), self.night)
        self.assertEqual(payload["counts"]["done"], 1)
        self.assertEqual(payload["counts"]["running"], 1)
        self.assertEqual(set(payload["agents"]), {"claude", "codex"})
        self.assertEqual(payload["window"]["timezone"], "America/Cuiaba")
        self.assertNotIn("DO_NOT_PUBLISH", json.dumps(payload))
        self.assertEqual(payload["agents"]["claude"]["completed"], 1)
        self.assertIsNone(payload["agents"]["codex"]["tasks_per_100k_tokens"])

    def test_html_escapes_untrusted_issue_titles_and_has_no_javascript(self):
        seed(self.db, [{
            "id": "untrusted", "title": '<script>alert("hacked")</script> task',
            "scope": ["src/nivon/m.py"]
        }])
        payload = summary(report(self.db), self.night)
        html = render_html(payload)
        self.assertNotIn('<script>', html)
        self.assertNotIn('<script>alert', html)
        self.assertIn("&lt;script&gt;", html)
        self.assertIn("Content-Security-Policy", html)
        self.assertNotIn("<iframe", html)
        self.assertNotIn("<img", html)
        self.assertNotIn("<link", html)
        self.assertNotIn("onclick=", html)

    def test_private_file_does_not_overwrite_symlink(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "report.html"
            saved = write_private(path, "<h1>NIVON</h1>")
            self.assertEqual(saved.read_text(encoding="utf-8"), "<h1>NIVON</h1>")
            if os.name == "posix":
                self.assertEqual(saved.stat().st_mode & 0o777, 0o600)
            target = Path(tmp) / "original"
            target.write_text("KEEP", encoding="utf-8")
            path.unlink()
            path.symlink_to(target)
            with self.assertRaisesRegex(ValueError, "symlink"):
                write_private(path, "should never replace link")
            self.assertEqual(target.read_text(encoding="utf-8"), "KEEP")

    def test_cli_json_and_html_without_external_calls(self):
        output = self.root / "index.html"
        with patch("nivon.dueto_painel.night_status", return_value=self.night), \
             patch("nivon.dueto_painel.default_db", return_value=self.database):
            self.assertEqual(main(["json"]), 0)
            self.assertEqual(main(["html", "--output", str(output)]), 0)
        self.assertIn("Dueto de Desenvolvimento", output.read_text(encoding="utf-8"))
        self.assertTrue(output.is_file())

    def test_no_synthetic_tokens_masquerading_as_measured(self):
        seed(self.db, [{
            "id": "metric", "title": "Medir consumo real",
            "scope": ["tests/test_metric.py"]
        }])
        claim(self.db, "claude")
        change(self.db, "metric", "claude", "done", "offline tests")
        payload = summary(report(self.db), self.night)
        self.assertIsNone(payload["agents"]["claude"]["tasks_per_100k_tokens"])
        self.assertEqual(payload["agents"]["claude"]["missing_usage"], 1)


if __name__ == "__main__":
    unittest.main()
