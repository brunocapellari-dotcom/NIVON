"""Inspeção GCS somente leitura — contrato do workflow dormiente."""
from pathlib import Path
import unittest

ROOT=Path(__file__).resolve().parents[1]
WORKFLOW=ROOT/".github/workflows/ivo-pam-gcs-inspecao-manual.yml"


class TestWorkflowGCSManual(unittest.TestCase):
    def setUp(self):
        self.text=WORKFLOW.read_text(encoding="utf-8")

    def test_sem_agendamento_push_ou_pr(self):
        header=self.text.split("permissions:",1)[0]
        self.assertIn("workflow_dispatch:",header)
        self.assertNotIn("schedule:",header)
        self.assertNotIn("push:",header)
        self.assertNotIn("pull_request:",header)
        self.assertNotIn("cron:",self.text)

    def test_so_main_com_homologacao_e_custo_aprovado(self):
        self.assertIn("github.ref == 'refs/heads/main'",self.text)
        self.assertIn("vars.NIVON_PAM_GCS_HOMOLOGADO == 'true'",self.text)
        self.assertIn("vars.NIVON_PAM_GCS_CUSTO_APROVADO == 'true'",self.text)
        for x in ("NIVON_PAM_GCS_BUCKET","NIVON_GCP_WIF_PROVIDER",
                  "NIVON_GCP_SERVICE_ACCOUNT"):
            self.assertIn(x,self.text)

    def test_wif_sem_chave_json_ou_billing(self):
        self.assertIn("id-token: write",self.text)
        self.assertIn("token_format: access_token",self.text)
        self.assertIn("google-github-actions/auth@",self.text)
        for forbidden in ("credentials_json:", "create-key",
                          "gcloud services enable", "gsutil mb",
                          "gcloud storage buckets create"):
            self.assertNotIn(forbidden,self.text)

    def test_nenhum_upload_download_ou_bootstrap_no_workflow(self):
        self.assertIn("python -m nivon.ivo_pam_storage_gcs estado",self.text)
        for forbidden in ("ivo_pam_storage_gcs upload",
                          "ivo_pam_storage_gcs recuperar", "--bootstrap",
                          "ivo_pam_operacao --modo PUBLICO_IBGE"):
            self.assertNotIn(forbidden,self.text)


if __name__=="__main__":
    unittest.main()
