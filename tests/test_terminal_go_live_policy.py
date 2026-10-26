"""Política de publicação: terminal privado, sem deploy automático e sem IAM aberto."""
import unittest
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
WF=ROOT/".github/workflows/nivon-terminal-go-live.yml"
DEPLOY=ROOT/"scripts/deploy_terminal_privado.sh"
DOCKER=ROOT/"infra/google_cloud/Dockerfile.terminal"
BUILD=ROOT/"infra/google_cloud/cloudbuild.terminal.yaml"


class TestGateGoLive(unittest.TestCase):
    def test_codigo_em_push_nao_publica_servico(self):
        s=WF.read_text(encoding="utf-8")
        body=s.split("  publicar-privado:",1)[1]
        cond=body.split("    runs-on:",1)[0]
        self.assertIn("github.ref == 'refs/heads/main'",cond)
        self.assertIn("github.event_name == 'workflow_dispatch'",cond)
        self.assertIn("inputs.confirmar_deploy == true",cond)
        self.assertNotIn("github.event_name == 'push'",cond)
        for name in ("NIVON_GO_LIVE_DEPLOY_APPROVED",
                     "NIVON_GCP_COST_REVIEWED",
                     "NIVON_TERMINAL_ARTIFACT_REPO",
                     "NIVON_TERMINAL_EXECUTION_SA"):
            self.assertIn(name,cond)
        test=s.split("  testes-e2e:",1)[1].split("  publicar-privado:",1)[0]
        self.assertNotIn("google-github-actions/auth",test)
        self.assertNotIn("id-token: write",test)
        self.assertIn("test_terminal_web.py",test)

    def test_deploy_nunca_deixa_service_publico(self):
        s=DEPLOY.read_text(encoding="utf-8")
        self.assertIn("--no-allow-unauthenticated",s)
        self.assertIn("SERVICO_ATUAL_COM_INVOKER_PUBLICO_NAO_ATUALIZAR",s)
        self.assertIn("GITHUB_REF",s)
        self.assertIn("NIVON_GO_LIVE_DEPLOY_APPROVED",s)
        self.assertIn("NIVON_GCP_COST_REVIEWED",s)
        self.assertIn("--min-instances=0",s)
        self.assertIn("--max-instances=1",s)
        self.assertIn("gcloud builds submit",s)
        self.assertIn("gcloud run deploy",s)
        for risk in ("gcloud run services add-iam-policy-binding",
                     "gcloud services enable",
                     "gcloud scheduler jobs create",
                     "gcloud iam service-accounts create",
                     "--allow-unauthenticated"):
            self.assertNotIn(risk,s)

    def test_imagem_nao_usa_usuario_root(self):
        s=DOCKER.read_text(encoding="utf-8")
        self.assertIn("USER 65532:65532",s)
        self.assertIn('nivon.terminal_web',s)
        self.assertNotIn("COPY . .",s)
        self.assertIn("' .[gcp] '".replace(" ",""),s.replace(" ",""))

    def test_build_nao_cria_repositorio(self):
        s=BUILD.read_text(encoding="utf-8")
        self.assertIn("gcr.io/cloud-builders/docker",s)
        self.assertIn("Dockerfile.terminal",s)
        self.assertIn("CLOUD_LOGGING_ONLY",s)


if __name__=="__main__":
    unittest.main()
