"""Gate de execucao: PR/push apenas testes, nunca carga ou DDL cloud."""
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1] / ".github" / "workflows"


def job_guard(filename, job):
    text = (ROOT / filename).read_text(encoding="utf-8")
    assert "  " + job + ":" in text
    after = text.split("  " + job + ":", 1)[1]
    return after.split("    runs-on:", 1)[0]


class TestGatesPrimeiraCarga(unittest.TestCase):
    def test_carga_piloto_exige_confirmacao_e_aprovacoes(self):
        cond = job_guard("nivon-antt-carga-unica-2026.yml", "executar-lote-unico")
        self.assertIn("github.ref == 'refs/heads/main'", cond)
        self.assertIn("github.event_name == 'workflow_dispatch'", cond)
        self.assertIn("inputs.confirmar_piloto_2026 == true", cond)
        self.assertNotIn("github.event_name == 'push'", cond)
        for var in ("NIVON_ZERO_COST_BQ_APPROVED",
                    "NIVON_RAW_ARCHIVE_APPROVED",
                    "NIVON_ANTT_FERROVIA_WRITE_APPROVED",
                    "NIVON_BQ_BOOTSTRAP_TABLE_APPROVED"):
            self.assertIn("vars."+var+" == 'true'",cond)

    def test_view_corredores_nao_publica_em_push(self):
        cond = job_guard("nivon-corredores-primeira-view-gcp.yml",
                         "publicar-e-medir")
        self.assertIn("github.ref == 'refs/heads/main'", cond)
        self.assertIn("github.event_name == 'workflow_dispatch'", cond)
        self.assertIn("inputs.confirmar_view == true", cond)
        self.assertIn("vars.NIVON_CORREDORES_VIEW_APPROVED == 'true'", cond)
        self.assertNotIn("github.event_name == 'push'", cond)

    def test_sem_escrita_para_eventos_de_pr(self):
        for filename, job in (
                ("nivon-antt-carga-unica-2026.yml", "executar-lote-unico"),
                ("nivon-corredores-primeira-view-gcp.yml", "publicar-e-medir")):
            with self.subTest(filename=filename):
                self.assertNotIn("github.event_name == 'pull_request'",
                                 job_guard(filename, job))


if __name__ == "__main__":
    unittest.main()
