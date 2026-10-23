"""Politica de seguranca para a migracao privada Neon -> BigQuery.

NENHUMA coleta privada ou escrita Cloud deve ocorrer num push/PR.
"""
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]
PATH = ROOT / ".github/workflows/nivon-gcp-migracao.yml"

class MigracaoWorkflowPolicy(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.texto = PATH.read_text(encoding="utf-8")
        cls.validar = cls.texto.split("  validar:",1)[1].split("  migrar:",1)[0]
        cls.migrar = cls.texto.split("  migrar:",1)[1]

    def test_push_e_pull_request_executam_apenas_validacao_offline(self):
        self.assertIn("  pull_request:", self.texto)
        self.assertIn("  push:", self.texto)
        self.assertIn("branches: [main]", self.texto)
        self.assertIn("  workflow_dispatch:", self.texto)
        self.assertIn("github.ref == 'refs/heads/main'", self.migrar)
        self.assertIn("github.event_name == 'workflow_dispatch'", self.migrar)
        self.assertIn("    needs: validar", self.migrar)

    def test_oidc_isolado_no_job_de_migracao(self):
        self.assertIn("permissions:\n  contents: read\n", self.texto)
        self.assertNotIn("id-token: write", self.validar)
        self.assertNotIn("google-github-actions/auth", self.validar)
        self.assertIn("      id-token: write", self.migrar)
        self.assertIn("google-github-actions/auth@v2", self.migrar)

    def test_escrita_requer_tres_aprovacoes_e_identidade(self):
        for gate in (
            "NIVON_GCP_WRITE_APPROVED == 'true'",
            "NIVON_GCP_COST_REVIEWED == 'true'",
            "NIVON_GCP_MIGRATION_APPROVED == 'true'",
            "NIVON_GCP_WIF_PROVIDER != ''",
            "NIVON_GCP_SERVICE_ACCOUNT != ''",
        ):
            with self.subTest(gate=gate):
                self.assertIn(gate, self.migrar)
        self.assertIn("if [ \"$NIVON_GCP_ENABLED\" = \"true\" ]; then", self.migrar)

    def test_origem_tem_lotes_isolados_e_sem_artifact(self):
        for fonte in ("imea","cepea","conab_safras","conab_balancos","conab_series"):
            self.assertIn(fonte,self.migrar)
        self.assertIn("trap 'rm -rf",self.migrar)
        self.assertIn("--validar --arquivo",self.migrar)
        self.assertIn("--carregar --arquivo",self.migrar)
        self.assertNotIn("actions/upload-artifact",self.migrar)

if __name__ == "__main__":
    unittest.main()
