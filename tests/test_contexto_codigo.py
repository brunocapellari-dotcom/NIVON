"""Tests for incremental AST index, safe bounded context capsule."""
import json
from pathlib import Path
import tempfile
import unittest

from nivon import contexto_codigo


class TestContextoCodigo(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        (self.root/"src/nivon").mkdir(parents=True)
        (self.root/"src/nivon/meteorologia.py").write_text(
            "class PrevisaoMeteorologica:\n    pass\n"
            "def calcular_precipitacao(dados):\n    return dados\n"
            "def _private():\n    pass\n", encoding="utf-8")
        self.cache = self.root / ".nivon-local/symbols.json"

    def tearDown(self):
        self.tmp.cleanup()

    def test_cache_is_incremental_and_invalidates_changes(self):
        first, reused = contexto_codigo.index(self.root, cache=self.cache)
        self.assertEqual(reused, 0)
        self.assertEqual(len(first), 1)
        second, reused = contexto_codigo.index(self.root, cache=self.cache)
        self.assertEqual(reused, 1)
        self.assertEqual(len(second), 1)
        f = self.root/"src/nivon/meteorologia.py"
        f.write_text(f.read_text(encoding="utf-8")+"\ndef adicional():\n    pass\n", encoding="utf-8")
        updated, reused = contexto_codigo.index(self.root, cache=self.cache)
        self.assertEqual(reused, 0)
        self.assertIn("adicional", [x["name"] for x in updated["src/nivon/meteorologia.py"]["symbols"]])

    def test_lookup_and_capsule_are_bounded(self):
        matches = contexto_codigo.lookup("Previsao", root=self.root, cache=self.cache)
        self.assertEqual(matches[0]["name"], "PrevisaoMeteorologica")
        self.assertEqual(contexto_codigo.lookup("_private", root=self.root, cache=self.cache), [])
        note = contexto_codigo.capsule({"title":"Corrigir precipitacao",
             "scope": '["src/nivon/meteorologia.py"]'}, root=self.root)
        self.assertIn("calcular_precipitacao", note)
        self.assertLessEqual(len(note), 500)

    def test_no_untrusted_code_execution(self):
        f = self.root/"src/nivon/meteorologia.py"
        f.write_text("import os\nos.system('echo unsafe')\ndef safe(): pass\n", encoding="utf-8")
        values, digest = contexto_codigo.symbols(f)
        self.assertEqual([x["name"] for x in values], ["safe"])
        self.assertEqual(len(digest), 64)


if __name__ == "__main__":
    unittest.main()
