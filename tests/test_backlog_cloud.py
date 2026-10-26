"""Fila NIVON: validação offline e escolha de tarefas sem chamar agentes."""
import json
from pathlib import Path
import tempfile
import unittest

from nivon import backlog_cloud


class TestBacklogCloud(unittest.TestCase):
    def test_real_manifest_is_valid_and_go_live_first(self):
        rows = backlog_cloud.load()
        self.assertGreaterEqual(len(rows), 30)
        issues = {r["issue"] for r in rows}
        self.assertEqual(len(issues), len(rows))
        self.assertTrue({281, 286, 287, 288, 289, 290, 291, 292, 296}.issubset(issues))
        self.assertEqual(next(r for r in rows if r["issue"] == 286)["priority"], "P0")
        self.assertEqual(next(r for r in rows if r["issue"] == 281)["readiness"], "external_gate")

    def test_codex_selection_disjoint_and_never_picks_human_external_gate(self):
        rows = backlog_cloud.load()
        ready = backlog_cloud.select(rows, agent="codex", limit=10)
        self.assertGreaterEqual(len(ready), 4)
        self.assertTrue(all(r["preferred_agent"] == "codex" for r in ready))
        self.assertNotIn(281, [r["issue"] for r in ready])
        paths = [p for task in ready for p in task["files"]]
        self.assertEqual(len(paths), len(set(paths)))

    def test_invalid_paths_and_duplicate_issue_rejected(self):
        rows = backlog_cloud.load()
        invalid = rows[0].copy()
        invalid["files"] = ["/etc/passwd"]
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "manifest.json"
            original = json.loads(backlog_cloud.DEFAULT_FILE.read_text(encoding="utf-8"))
            original["tasks"][0] = invalid
            path.write_text(json.dumps(original), encoding="utf-8")
            with self.assertRaises(ValueError):
                backlog_cloud.load(path)
            original["tasks"][0] = rows[0]
            original["tasks"][1]["issue"] = original["tasks"][0]["issue"]
            original["tasks"][1]["issue_url"] = original["tasks"][0]["issue_url"]
            path.write_text(json.dumps(original), encoding="utf-8")
            with self.assertRaises(ValueError):
                backlog_cloud.load(path)

    def test_cycle_detection_and_readiness_gate(self):
        rows = backlog_cloud.load()
        with self.assertRaises(ValueError):
            backlog_cloud.select(rows, agent="Codex", limit=1)
        with self.assertRaises(ValueError):
            backlog_cloud.select(rows, agent="codex", limit=0)
        modified = [r.copy() for r in rows]
        modified[0]["depends_on"] = [modified[1]["id"]]
        modified[1]["depends_on"] = [modified[0]["id"]]
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "manifest.json"
            obj = json.loads(backlog_cloud.DEFAULT_FILE.read_text(encoding="utf-8"))
            obj["tasks"] = modified
            path.write_text(json.dumps(obj), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "Ciclo"):
                backlog_cloud.load(path)


if __name__ == "__main__":
    unittest.main()
