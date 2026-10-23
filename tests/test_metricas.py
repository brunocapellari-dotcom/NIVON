"""Contract fixtures of Claude JSON and Codex JSONL usage, without actual model calls."""
import json
from pathlib import Path
import tempfile
import unittest

from nivon.metricas import MAX_LOG_BYTES, parse_file, parse_text


class TestMetricas(unittest.TestCase):
    def test_claude_cache_counts_as_processed_input(self):
        log = json.dumps({"type": "result", "usage": {
            "input_tokens": 100, "cache_read_input_tokens": 800,
            "cache_creation_input_tokens": 50, "output_tokens": 30}})
        data = parse_text(log, "claude")
        self.assertEqual(data["input"], 950)
        self.assertEqual(data["output"], 30)
        self.assertEqual(data["cached_input"], 800)
        self.assertEqual(data["cache_creation"], 50)

    def test_claude_missing_cache_remains_unknown(self):
        data = parse_text('{"type":"result","usage":{"input_tokens":2,"output_tokens":4}}',
                          "claude")
        self.assertEqual(data["input"], 2)
        self.assertIsNone(data["cached_input"])

    def test_codex_multiple_completed_turns_and_cumulative_cache(self):
        stream = "\n".join([
            json.dumps({"type": "thread.started"}),
            json.dumps({"type": "turn.completed", "usage": {
                "input_tokens": 300, "cached_input_tokens": 200,
                "output_tokens": 40}}),
            json.dumps({"type": "item.completed", "item": {
                "type": "agent_message", "text": "not usage"}}),
            json.dumps({"type": "turn.completed", "usage": {
                "input_tokens": 450, "cached_input_tokens": 300,
                "output_tokens": 55}})])
        data = parse_text(stream, "codex")
        self.assertEqual((data["input"], data["output"], data["cached_input"]), (750, 95, 500))
        self.assertEqual(data["completed_turns"], 2)

    def test_unknown_cache_if_any_turn_has_unknown(self):
        stream = "\n".join([
            '{"type":"turn.completed","usage":{"input_tokens":12,"output_tokens":8}}',
            '{"type":"turn.completed","usage":{"input_tokens":33,"cached_input_tokens":20,"output_tokens":5}}',
        ])
        data = parse_text(stream, "codex")
        self.assertEqual(data["input"], 45)
        self.assertIsNone(data["cached_input"])

    def test_no_fabricated_data_and_invalid_types(self):
        for text in ('{"type":"turn.failed"}', "garbled", "",
                     '{"type":"turn.completed","usage":{"input_tokens":-1,"output_tokens":3}}'):
            self.assertIsNone(parse_text(text, "codex"))
        self.assertIsNone(parse_text('{"usage":{"input_tokens":false,"output_tokens":1}}', "claude"))
        self.assertIsNone(parse_text('{"type":"turn.completed","usage":{"input_tokens":2,"cached_input_tokens":5,"output_tokens":1}}', "codex"))
        with self.assertRaises(ValueError):
            parse_text("{}", "other")

    def test_read_file_size_cap_and_missing(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "session.jsonl"
            path.write_text(
                '{"type":"turn.completed","usage":{"input_tokens":22,"cached_input_tokens":1,"output_tokens":4}}',
                encoding="utf-8")
            self.assertEqual(parse_file(path, "codex")["input"], 22)
            self.assertIsNone(parse_file(Path(tmp) / "missing", "codex"))
            with path.open("wb") as f:
                f.truncate(MAX_LOG_BYTES + 1)
            self.assertIsNone(parse_file(path, "codex"))


if __name__ == "__main__":
    unittest.main()
