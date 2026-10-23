"""Regressão: primeira carga ANTT 2026 não pode escrever por mero push."""
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]
FILE = ROOT / ".github/workflows/nivon-antt-carga-unica-2026.yml"


class TestPoliticaPrimeiraCargaANTT(unittest.TestCase):
    def test_push_e_pr_rodando_apenas_testes(self):
        text = FILE.read_text(encoding="utf-8")
        self.assertIn("  pull_request:", text)
        self.assertIn("  push:", text)
        self.assertIn("  testar:", text)
        runnable = text.split("  executar-lote-unico:", 1)[1]
        clause = runnable.split("    runs-on:", 1)[0]
        self.assertIn("github.ref == 'refs/heads/main'", clause)
        self.assertIn("github.event_name == 'workflow_dispatch'", clause)
        self.assertIn("inputs.confirmar_piloto_2026 == true", clause)
        self.assertNotIn("github.event_name == 'push'", clause)
        self.assertNotIn("github.event_name != 'pull_request'", clause)

    def test_workflow_necessita_confirmação_explicita(self):
        text = FILE.read_text(encoding="utf-8")
        self.assertIn("      confirmar_piloto_2026:", text)
        self.assertIn("        default: false", text)
        job = text.split("  executar-lote-unico:", 1)[1]
        self.assertIn("    needs: testar", job)
        self.assertIn("--live --confirmar-piloto-2026", job)
        self.assertIn("      id-token: write", job)
        self.assertIn("group: nivon-carga-piloto-antt-2026", text)
        self.assertIn("cancel-in-progress: false", text)

if __name__ == "__main__":
    unittest.main()
