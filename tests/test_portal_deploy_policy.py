"""Cloud Run portal: contrato de no-bypass e custos opt-in."""
from pathlib import Path
import unittest
ROOT=Path(__file__).resolve().parents[1]

class PortalDeployPolicy(unittest.TestCase):
    def test_workflow_nao_faz_deploy_ao_abrir_pr(self):
        wf=(ROOT/".github/workflows/portal-cloudrun-privado.yml").read_text()
        shell=(ROOT/"scripts/nivon_portal_cloudrun_deploy.sh").read_text()
        docker=(ROOT/"infra/google_cloud/Dockerfile.portal").read_text()
        cloudbuild=(ROOT/"infra/google_cloud/cloudbuild.portal.yaml").read_text()
        for token in ("workflow_dispatch:","inputs.executar_deploy == true",
                      "github.ref == 'refs/heads/main'",
                      "NIVON_GCP_COST_REVIEWED",
                      "NIVON_PORTAL_DEPLOY_APPROVED",
                      "NIVON_PORTAL_GCS_READ_APPROVED",
                      "NIVON_PORTAL_PRIVATE_BUCKET_REVIEWED",
                      "NIVON_PORTAL_ARTIFACT_REPO",
                      "NIVON_PORTAL_SERVICE_ACCOUNT",
                      "environment: nivon-gcp-producao","id-token: write"):
            with self.subTest(token=token):
                self.assertIn(token,wf)
        self.assertNotIn("schedule:",wf)
        self.assertNotIn("push:\n",wf)
        self.assertIn("--no-allow-unauthenticated",shell)
        self.assertIn("services get-iam-policy",shell)
        self.assertIn("allAuthenticatedUsers",shell)
        self.assertIn("--min-instances=0",shell)
        self.assertIn("--max-instances=1",shell)
        self.assertIn("gcloud builds submit",shell)
        self.assertIn("gcloud run deploy",shell)
        self.assertNotIn("services enable",shell)
        self.assertNotIn("set-iam-policy",shell)
        self.assertNotIn("gcloud scheduler",shell.lower())
        self.assertNotIn("cloudscheduler.googleapis.com",shell.lower())
        self.assertIn("USER 65532:65532",docker)
        self.assertIn("portal_gcs:application",docker)
        self.assertIn("Dockerfile.portal",cloudbuild)
        self.assertIn("_IMAGE_URI",cloudbuild)

if __name__=="__main__":
    unittest.main()
