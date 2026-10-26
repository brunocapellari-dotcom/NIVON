"""Regras de CI e write-gate para réplica hidroviária ANTAQ de TERCEIRO."""
from pathlib import Path
import unittest

ROOT=Path(__file__).resolve().parents[1]
WF=ROOT/".github/workflows/nivon-antaq-secundaria-gcp-2025.yml"


class TestWorkflowReplicaANTAQ(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.text=WF.read_text(encoding="utf-8")
        cls.teste=cls.text.split("  testar-contrato:",1)[1].split("  publicar-somente-terceiro:",1)[0]
        cls.escrita=cls.text.split("  publicar-somente-terceiro:",1)[1]
        cls.cond=cls.escrita.split("    runs-on:",1)[0]

    def test_push_e_pr_so_rodar_ci(self):
        self.assertIn("  push:",self.text)
        self.assertIn("  pull_request:",self.text)
        self.assertIn("  workflow_dispatch:",self.text)
        self.assertIn("    needs: testar-contrato",self.escrita)
        self.assertIn("github.event_name == 'workflow_dispatch'",self.cond)
        self.assertNotIn("github.event_name == 'push'",self.cond)
        self.assertNotIn("github.event_name != 'pull_request'",self.cond)
        self.assertIn("default: false",self.text)
        self.assertIn("inputs.aceitar_fonte_secundaria == true",self.cond)

    def test_exigir_aprovacao_risco_fonte_e_custos(self):
        for chave in (
            "vars.NIVON_ANTAQ_REPLICA_WRITE_APPROVED == 'true'",
            "vars.NIVON_GCP_COST_REVIEWED == 'true'",
            "vars.NIVON_ANTAQ_REPLICA_BOOTSTRAP_APPROVED == 'true'",
            "vars.NIVON_GCP_PROVIDER != ''",
            "vars.NIVON_GCP_SERVICE_ACCOUNT != ''",
            "github.ref == 'refs/heads/main'",
        ):
            with self.subTest(chave=chave):self.assertIn(chave,self.cond)

    def test_oidc_so_no_job_que_precisa(self):
        cabecalho=self.text.split("jobs:",1)[0]
        self.assertNotIn("id-token: write",cabecalho)
        self.assertNotIn("id-token: write",self.teste)
        self.assertIn("      id-token: write",self.escrita)
        self.assertIn("NIVON_GCP_PROVIDER",self.escrita)
        self.assertIn("PYTHONPATH: src",self.escrita)
        self.assertIn("--permitir-criar-tabela",self.escrita)
        self.assertIn("  validar-replica-real-sem-gcp:",self.teste)
        self.assertNotIn("google-github-actions/auth",self.teste)

    def test_replicacao_nunca_e_fonte_oficial(self):
        self.assertIn("DERIVADO_DE_TERCEIRO_NAO_HOMOLOGADO",
                      (ROOT/"src/nivon/antaq_secundaria_gcp_2025.py").read_text(encoding="utf-8"))
        self.assertIn("NÃO é total oficial homologado",self.escrita)
        self.assertIn("não",self.escrita.lower())

if __name__=="__main__":
    unittest.main()
