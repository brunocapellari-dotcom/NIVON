"""Go-live: bloquear disparos pagos automaticos antes de IAM/billing aprovado."""
import unittest
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]/".github"/"workflows"

class GoLiveCostPolicy(unittest.TestCase):
    def test_internal_stays_off_on_push_and_requires_authorization(self):
        text=(ROOT/"nivon-go-live-interno.yml").read_text(encoding="utf-8")
        job=text.split("  primeira-publicacao:",1)[1].split("    runs-on:",1)[0]
        self.assertNotIn("github.event_name == 'push'",job)
        self.assertIn("NIVON_PAINEL_INTERNO_WRITE_APPROVED == 'true'",job)
        self.assertIn("NIVON_GCP_COST_REVIEWED == 'true'",job)
        self.assertIn("inputs.publicar == true",job)
        self.assertIn("NIVON_PAINEL_INTERNO_AGENDADO == 'true'",job)
        self.assertIn("github.event_name == 'workflow_dispatch'",job)

    def test_job_publicacao_tem_id_token_isolado(self):
        text=(ROOT/"nivon-go-live-interno.yml").read_text(encoding="utf-8")
        quality=text.split("  qualidade:",1)[1].split("  primeira-publicacao:",1)[0]
        publish=text.split("  primeira-publicacao:",1)[1]
        self.assertNotIn("id-token: write",quality)
        self.assertIn("id-token: write",publish)

    def test_piloto_real_read_uses_manual_double_gate(self):
        text=(ROOT/"nivon-terminal-piloto-real.yml").read_text(encoding="utf-8")
        job=text.split("  piloto-real:",1)[1].split("    runs-on:",1)[0]
        self.assertNotIn("  push:",text)
        self.assertIn("github.event_name == 'workflow_dispatch'",job)
        self.assertIn("NIVON_TERMINAL_READ_APPROVED == 'true'",job)
        self.assertIn("NIVON_GCP_COST_REVIEWED == 'true'",job)

if __name__=="__main__":
    unittest.main()
