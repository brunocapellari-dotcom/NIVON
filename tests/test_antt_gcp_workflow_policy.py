"""Valida condicoes fail-closed da tarefa agendada ferroviaria no GCP."""
import unittest
from pathlib import Path

WORKFLOW = Path(__file__).resolve().parents[1] / ".github/workflows/antt-ferrovia-gcp.yml"
CORE = Path(__file__).resolve().parents[1] / ".github/workflows/coleta-recorrente-fontes.yml"


class Policy(unittest.TestCase):
    def test_variaveis_coincidem_com_nucleo_gcp(self):
        texto=WORKFLOW.read_text(encoding="utf-8")
        core=CORE.read_text(encoding="utf-8")
        for v in ("NIVON_BQ_PROJECT", "NIVON_BQ_DATASET",
                  "NIVON_GCS_BUCKET","NIVON_GCP_PROVIDER",
                  "NIVON_GCP_SERVICE_ACCOUNT",
                  "NIVON_ZERO_COST_BQ_APPROVED",
                  "NIVON_RAW_ARCHIVE_APPROVED",
                  "NIVON_BQ_BOOTSTRAP_TABLE_APPROVED"):
            with self.subTest(v=v):
                self.assertIn(v, texto)
                self.assertIn(v, core)
        self.assertNotIn("NIVON_GCP_PROJECT_ID", texto)
        self.assertNotIn("NIVON_GCP_WIF_PROVIDER", texto)

    def test_agendamento_so_main_com_2_aprovacoes(self):
        texto=WORKFLOW.read_text(encoding="utf-8")
        job=texto.split("  coletar-e-persistir:",1)[1]
        condicao=job.split("    runs-on:",1)[0]
        self.assertIn("github.ref == 'refs/heads/main'",condicao)
        self.assertIn("vars.NIVON_ZERO_COST_BQ_APPROVED == 'true'",condicao)
        self.assertIn("vars.NIVON_RAW_ARCHIVE_APPROVED == 'true'",condicao)
        self.assertIn("inputs.modo == 'live'",condicao)
        self.assertNotIn("pull_request",texto)
        self.assertIn("NIVON_BOOTSTRAP_TABLE_APPROVED",job)
        self.assertIn("cmd.append('--permitir-criar-tabela')", job)

    def test_preflight_nao_tem_id_token_nem_auth(self):
        texto=WORKFLOW.read_text(encoding="utf-8")
        preflight=texto.split("  preflight:",1)[1].split("  coletar-e-persistir:",1)[0]
        self.assertNotIn("google-github-actions/auth",preflight)
        self.assertNotIn("id-token: write",preflight)
        self.assertIn("GCP_PENDENTE_CONFIGURACAO_OU_APROVACAO",preflight)


if __name__=="__main__":
    unittest.main()
