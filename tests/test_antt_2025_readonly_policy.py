"""Regras para extração ANTT 2025 sem custos de escrita GCS/BigQuery."""
from pathlib import Path
import unittest

WORKFLOW=(Path(__file__).resolve().parents[1] / ".github/workflows/antt-ferrovia-2025-readonly.yml")


class TestReadOnly2025(unittest.TestCase):
    def test_fluxo_2025_apenas_metadados(self):
        s=WORKFLOW.read_text(encoding="utf-8")
        self.assertIn("--inicio 2025 --fim 2025",s)
        self.assertIn("--ano 2025",s)
        self.assertIn("nivon.antt_gcp_preparar_piloto",s)
        self.assertIn("--usar-url-verificada-contingencia",s)
        self.assertIn("gravacoes_realizadas",s)
        self.assertIn("jobs_bigquery_criados",s)
        # Nenhum dos módulos de escrita deve ser invocado diretamente.
        for unsafe in ("nivon.antt_gcp_piloto_2026","nivon.antt_gcp_pipeline",
                       "nivon.antt_bigquery", "nivon.antt_gcs",
                       "--permitir-criar-tabela","--confirmar-piloto-2026",
                       "load_table_from_json", "CREATE TABLE"):
            with self.subTest(unsafe=unsafe):
                self.assertNotIn(unsafe,s)

    def test_pr_nao_acessa_oidc(self):
        s=WORKFLOW.read_text(encoding="utf-8")
        j=s.split("  preparar_2025:",1)[1].split("    runs-on:",1)[0]
        self.assertIn("github.ref == 'refs/heads/main'",j)
        self.assertIn("github.event_name != 'pull_request'",j)
        self.assertIn("needs: validar",j)
        self.assertIn("persist-credentials: false",s)


if __name__ == "__main__":
    unittest.main()
