"""Gate de execução cloud da ANP: workflow inerte em PRs e sem custo implícito.

A suíte não simula execução de IAM; verifica explicitamente as barreiras
determinísticas no arquivo de configuração versionado.
"""
from pathlib import Path
import unittest


WORKFLOW = (Path(__file__).resolve().parents[1] /
            ".github" / "workflows" / "anp-lpc-gcp.yml")


class TestWorkflowANPGCP(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.yaml = WORKFLOW.read_text(encoding="utf-8")

    def test_disparo_requer_main_e_autorizacoes_distintas(self):
        texto = self.yaml
        self.assertIn("github.ref == 'refs/heads/main'", texto)
        for gate in (
            "NIVON_ANP_LPC_COST_LIMIT_APPROVED",
            "NIVON_ANP_LPC_WRITE_APPROVED",
            "NIVON_ANP_LPC_RECURRING_APPROVED",
            "NIVON_RAW_ARCHIVE_APPROVED",
        ):
            with self.subTest(gate=gate):
                self.assertIn("vars."+gate+" == 'true'",texto)
        self.assertIn("github.event_name == 'workflow_dispatch'",texto)
        self.assertIn("github.event_name == 'schedule'",texto)
        self.assertNotIn("pull_request:",texto)

    def test_sem_criacao_de_recursos_e_sem_chaves_persistentes(self):
        texto=self.yaml
        self.assertIn("google-github-actions/auth@",texto)
        self.assertIn("persist-credentials: false",texto)
        self.assertIn("id-token: write",texto)
        self.assertIn("environment: nivon-gcp-producao",texto)
        for proibido in (
            "gcloud storage buckets create",
            "gcloud services enable",
            "gcloud beta billing",
            "terraform apply",
            "google-service-account-json",
            "credentials_json:",
            "GOOGLE_APPLICATION_CREDENTIALS:",
        ):
            with self.subTest(proibido=proibido):
                self.assertNotIn(proibido,texto)
        self.assertIn("public_access_prevention!='enforced'",texto)

    def test_comando_reusa_o_ciclo_e_identidade_gcp_existentes(self):
        texto=self.yaml
        self.assertIn("--modo ciclo-gcs",texto)
        self.assertIn("vars.NIVON_GCS_BUCKET",texto)
        self.assertIn("vars.NIVON_GCP_PROVIDER",texto)
        self.assertIn("vars.NIVON_GCP_SERVICE_ACCOUNT",texto)
        self.assertIn("ANO=\"$(date -u +%Y)\"",texto)
        self.assertIn("concurrency:",texto)
        self.assertIn("cancel-in-progress: false",texto)


if __name__=="__main__":
    unittest.main()
