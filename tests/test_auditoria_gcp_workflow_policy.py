"""O monitor GCP recorrente jamais cria recursos ou executa escrita em PR."""
from pathlib import Path
import unittest

WORKFLOW = (Path(__file__).resolve().parents[1]
            / ".github/workflows/auditoria-gcp-readonly.yml")


class AuditoriaGCPWorkflowPolicy(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.text = WORKFLOW.read_text(encoding="utf-8")
        cls.offline = cls.text.split("  contrato:", 1)[1].split("  metadados-reais:", 1)[0]
        cls.live = cls.text.split("  metadados-reais:", 1)[1]

    def test_recorrencia_apenas_leitura_e_main(self):
        self.assertIn("  schedule:", self.text)
        self.assertIn("    - cron: '30 12 * * 1-5'", self.text)
        self.assertIn("github.ref == 'refs/heads/main'", self.live)
        self.assertIn("github.event_name != 'pull_request'", self.live)
        self.assertIn("    needs: contrato", self.live)
        self.assertIn("group: nivon-auditoria-gcp-readonly", self.text)

    def test_pr_nao_recebe_oidc_nem_toca_cloud(self):
        root=self.text.split("jobs:",1)[0]
        self.assertNotIn("id-token: write", root)
        self.assertNotIn("id-token: write", self.offline)
        self.assertNotIn("google-github-actions/auth", self.offline)
        self.assertIn("      id-token: write",self.live)
        self.assertIn("vars.NIVON_GCP_PROVIDER",self.live)
        self.assertIn("vars.NIVON_GCP_SERVICE_ACCOUNT",self.live)

    def test_auditoria_nao_pode_fingir_homologacao(self):
        self.assertIn("-m nivon.auditoria_gcp_readonly", self.live)
        self.assertIn("--executar >",self.live)
        self.assertIn("TABELAS_AGRICOLAS_PENDENTES_OU_DIVERGENTES",self.live)
        self.assertIn("não comprova permissão de escrita", self.live)
        for token in ("--aplicar", "--criar-tabela", "bigquery.jobs.create", "load_table_from_file"):
            self.assertNotIn(token,self.live)

if __name__ == "__main__":
    unittest.main()
