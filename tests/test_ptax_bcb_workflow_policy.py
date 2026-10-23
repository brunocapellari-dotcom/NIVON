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
                      "NIVON_GCP_WIF_PROVIDER != ''",
                      "NIVON_GCP_SERVICE_ACCOUNT != ''",
                      "      id-token: write"):
            self.assertIn(regra,ingestao)
        self.assertIn("args+=(--carregar)",ingestao)
        self.assertIn('if [ "$NIVON_GCP_ENABLED" = "true" ]',ingestao)
        self.assertIn("trap 'rm -f",ingestao)

    def test_wif_bootstrap_restringe_repo_branch_e_workflow(self):
        self.assertIn('PTAX_DIRECT_WORKFLOW="${REPO}/.github/workflows/ptax-bcb-direto-gcp.yml@refs/heads/main"',BOOT)
        self.assertIn("assertion.workflow_ref=='${PTAX_DIRECT_WORKFLOW}'",BOOT)
        self.assertIn("assertion.repository=='${REPO}'",BOOT)
        self.assertIn("assertion.ref=='refs/heads/main'",BOOT)
        self.assertIn("PROVEDOR_PREEXISTENTE_COM_CONDICAO_DIFERENTE",BOOT)

if __name__=="__main__":
    unittest.main()
