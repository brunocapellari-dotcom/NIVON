"""Nao habilitar dois escritores PTAX para a mesma tabela BigQuery."""
from pathlib import Path
import unittest

ROOT=Path(__file__).resolve().parents[1]
DIRETO=(ROOT/".github/workflows/ptax-bcb-direto-gcp.yml").read_text(encoding="utf-8")
NEON=(ROOT/".github/workflows/ptax-neon-private-export.yml").read_text(encoding="utf-8")
BOOT=(ROOT/"scripts/bootstrap_nivon_gcp.sh").read_text(encoding="utf-8")


class PoliticaEscritorUnicoPTAX(unittest.TestCase):
    def test_bcb_so_consulta_automaticamente_em_main(self):
        self.assertIn("  schedule:",DIRETO)
        self.assertIn("  workflow_dispatch:",DIRETO)
        self.assertIn("github.ref == 'refs/heads/main'",DIRETO)
        self.assertIn("github.event_name == 'schedule'",DIRETO)
        self.assertIn("github.event_name == 'workflow_dispatch'",DIRETO)
        self.assertIn("    needs: validar",DIRETO)

    def test_exclusividade_bcb_e_ponte_neon(self):
        chave="NIVON_PTAX_DIRECT_WRITER_APPROVED"
        self.assertIn("vars."+chave+" == 'true'",DIRETO)
        self.assertIn("vars."+chave+" != 'true'",NEON)
        self.assertIn("group: nivon-ptax-neon-bigquery",DIRETO)
        self.assertIn("group: nivon-ptax-neon-bigquery",NEON)

    def test_custo_e_identidade_no_bcb(self):
        ingestao=DIRETO.split("  consultar_bcb:",1)[1]
        offline=DIRETO.split("  validar:",1)[1].split("  consultar_bcb:",1)[0]
        self.assertNotIn("id-token: write",offline)
        self.assertNotIn("google-github-actions/auth",offline)
        for regra in ("NIVON_GCP_WRITE_APPROVED == 'true'",
                      "NIVON_GCP_COST_REVIEWED == 'true'",
                      "NIVON_GCP_PROVIDER != ''",
                      "NIVON_GCP_SERVICE_ACCOUNT != ''",
                      "      id-token: write"):
            self.assertIn(regra,ingestao)
        self.assertIn("args+=(--carregar)",ingestao)
        self.assertIn('if [ "$NIVON_GCP_ENABLED" = "true" ]',ingestao)
        self.assertIn("trap 'rm -f",ingestao)

    def test_wif_bootstrap_restringe_repo_branch_e_workflow(self):
        self.assertIn('PROVIDER="github-actions"',BOOT)
        self.assertIn('SA_NAME="nivon-coletor-de-dados"',BOOT)
        self.assertIn('NIVON_GCP_PROVIDER=$WIF_NAME',BOOT)
        self.assertIn("assertion.repository",BOOT)
        self.assertIn("assertion.ref",BOOT)
        self.assertIn("refs/heads/main",BOOT)
        self.assertIn("WIF_CONDICAO_NAO_HOMOLOGADA",BOOT)
        self.assertIn("normalized!=allowed",BOOT)
        self.assertNotIn("gcloud services enable",BOOT)
        self.assertNotIn("gcloud projects add-iam-policy-binding",BOOT)
        self.assertNotIn("providers create-oidc",BOOT)
        self.assertNotIn("service-accounts create",BOOT)
        self.assertNotIn("iam.workloadIdentityUser",BOOT)

    def test_migracoes_reutilizam_provider_que_ja_autenticou_no_cloud(self):
        workflows = [
            ".github/workflows/ptax-neon-private-export.yml",
            ".github/workflows/ptax-bcb-direto-gcp.yml",
            ".github/workflows/nivon-gcp-migracao.yml",
            ".github/workflows/nivon-gcp-zarc.yml",
        ]
        fonte_validada = (ROOT/".github/workflows/nivon-gcp-conexao-readonly.yml").read_text(encoding="utf-8")
        self.assertIn("vars.NIVON_GCP_PROVIDER", fonte_validada)
        for path in workflows:
            with self.subTest(workflow=path):
                workflow = (ROOT/path).read_text(encoding="utf-8")
                self.assertIn("vars.NIVON_GCP_PROVIDER", workflow)
                self.assertNotIn("NIVON_GCP_WIF_PROVIDER", workflow)

    def test_zarc_sem_escrita_por_push_e_com_escopo_oitc_minimo(self):
        zarc = (ROOT/".github/workflows/nivon-gcp-zarc.yml").read_text(encoding="utf-8")
        offline = zarc.split("  testar:",1)[1].split("  migrar:",1)[0]
        job = zarc.split("  migrar:",1)[1]
        condition = job.split("    needs:",1)[0]
        self.assertIn("github.ref == 'refs/heads/main'",condition)
        self.assertIn("github.event_name == 'workflow_dispatch'",condition)
        self.assertNotIn("id-token: write",offline)
        self.assertIn("      id-token: write",job)
        self.assertIn("NIVON_GCP_PROVIDER",job)
        self.assertIn("NIVON_GCP_COST_REVIEWED",job)
        self.assertIn("NIVON_GCP_WRITE_APPROVED",job)

if __name__=="__main__":
    unittest.main()
