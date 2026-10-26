"""Comprova read-only da auditoria de go-live no commit atual."""
from pathlib import Path
import unittest

PATH=Path(__file__).resolve().parents[1]/".github/workflows/nivon-terminal-piloto-real.yml"

class GateReadiness(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.src=PATH.read_text(encoding="utf8")

    def test_checkout_commit_atual_sem_pin_obsoleto(self):
        self.assertNotIn("ref: 1abd6d5daa032797b6d377db572878a3862b243d",self.src)
        self.assertIn("Testar API, isolamento e comportamento",self.src)
        self.assertIn("NIVON_TERMINAL_GATE=",self.src)

    def test_pr_so_executa_validacao_offline(self):
        self.assertIn("  pull_request:",self.src)
        self.assertIn("  validar-preflight:",self.src)
        self.assertIn("  piloto-real:",self.src)
        job=self.src.split("  validar-preflight:",1)[1].split("  piloto-real:",1)[0]
        self.assertNotIn("google-github-actions/auth",job)
        self.assertNotIn("gcloud",job)
        actual=self.src.split("  piloto-real:",1)[1].split("    runs-on:",1)[0]
        self.assertIn("github.ref == 'refs/heads/main'",actual)
        self.assertIn("github.event_name != 'pull_request'",actual)

    def test_preflight_nao_publica_nem_vaza_valor_da_variavel(self):
        self.assertIn("NIVON_GO_LIVE_PREFLIGHT=",self.src)
        self.assertIn("NIVON_GCP_COST_REVIEWED",self.src)
        self.assertIn("NIVON_TERMINAL_ARTIFACT_REPO",self.src)
        self.assertIn("NIVON_TERMINAL_EXECUTION_SA",self.src)
        self.assertIn("conta_de_faturamento_verificada",self.src)
        self.assertNotIn("gcloud run deploy",self.src)
        self.assertNotIn("gcloud builds submit",self.src)
        self.assertNotIn("gcloud services enable",self.src)

if __name__=="__main__":
    unittest.main()
