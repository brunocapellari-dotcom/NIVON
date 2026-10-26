"""Prova estática dos gates M1, sem GitHub, GCP, IAM ou rede."""
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]


class TestFluxoM1IAP(unittest.TestCase):
    def test_flag_iap_e_escala_minima(self):
        s = (ROOT / "scripts/deploy_terminal_privado.sh").read_text()
        for item in ("--iap", "--no-allow-unauthenticated",
                     "--min-instances=0", "--max-instances=1",
                     "conferir_politica_iap", "get-iam-policy"):
            self.assertIn(item, s)
        self.assertNotIn("gcloud run services add-iam-policy-binding", s)
        self.assertNotIn("gcloud iap web add-iam-policy-binding", s)

    def test_m1_nao_depende_de_snapshot_maritimo(self):
        s = (ROOT / "scripts/deploy_terminal_privado.sh").read_text()
        self.assertNotIn("from nivon.terminal_snapshot_gcs import ler_gcs", s)
        self.assertNotIn("LINEUP_' or", s)
        self.assertIn("vw_antt_ferrovia_od_atual", s)

    def test_ci_smoke_docker_e_aprovacao_manual(self):
        wf = (ROOT / ".github/workflows/nivon-terminal-go-live.yml").read_text()
        self.assertIn("testes-conteiner:", wf)
        self.assertIn("smoke_terminal_container.py", wf)
        self.assertIn("test_aceite_terminal_privado.py", wf)
        self.assertIn("docker build -f infra/google_cloud/Dockerfile.terminal", wf)
        self.assertIn("github.event_name == 'workflow_dispatch'", wf)
        self.assertIn("inputs.confirmar_deploy == true", wf)
        self.assertIn("NIVON_GCP_COST_REVIEWED", wf)
        self.assertIn("NIVON_GO_LIVE_DEPLOY_APPROVED", wf)


if __name__ == "__main__":
    unittest.main()
