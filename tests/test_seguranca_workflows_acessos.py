"""Gates estruturais: nenhum segredo em PR e nenhuma coleta involuntária."""
import unittest
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
MANUAL=(ROOT/".github/workflows/acessos-privados.yml").read_text(encoding="utf-8")
OFFLINE=(ROOT/".github/workflows/testes-acessos-isolados.yml").read_text(encoding="utf-8")


class TestSegurancaWorkflowsAcessos(unittest.TestCase):
    def test_manual_somente_workflow_dispatch_sem_outros_gatilhos(self):
        block=MANUAL.split("on:",1)[1].split("permissions:",1)[0]
        self.assertIn("workflow_dispatch:",block)
        for name in ("pull_request:", "pull_request_target:", "push:",
                     "schedule:", "workflow_run:", "repository_dispatch:"):
            self.assertNotIn(name,block)

    def test_manual_somente_main_e_environment_restrito(self):
        self.assertEqual(MANUAL.count("environment: nivon-fontes-privadas"),3)
        self.assertEqual(MANUAL.count("github.ref == 'refs/heads/main'"),3)
        self.assertIn("  contents: read",MANUAL)
        self.assertNotIn("contents: write",MANUAL)

    def test_preflight_padrao_live_explicitamente_opcional(self):
        self.assertIn("default: preflight",MANUAL)
        self.assertEqual(MANUAL.count("--preflight"),3)
        self.assertEqual(MANUAL.count("--live"),3)
        self.assertEqual(MANUAL.count('elif [ "$NIVON_ACCESS_MODE" = "live" ]; then'),3)

    def test_secret_menos_privilegios_sem_exportar_dados(self):
        for name in ("AGROBR_USDA_API_KEY","NIVON_ANA_IDENTIFICADOR",
                     "NIVON_ANA_SENHA","NIVON_INMET_BDMEP_URL"):
            self.assertIn("secrets."+name,MANUAL)
            self.assertNotIn("secrets."+name,OFFLINE)
        for forbidden in ("actions/upload-artifact","echo $","printenv",
                          "set -x","curl ","wget "):
            self.assertNotIn(forbidden,MANUAL)

    def test_ci_de_pr_somente_sintetica_e_read_only(self):
        block=OFFLINE.split("on:",1)[1].split("permissions:",1)[0]
        self.assertIn("pull_request:",block)
        self.assertNotIn("workflow_dispatch:",block)
        self.assertNotIn("push:",block)
        self.assertIn("  contents: read",OFFLINE)
        self.assertNotIn("secrets.",OFFLINE)
        self.assertNotIn(" --live",OFFLINE)
        self.assertIn("python -m unittest discover -s tests -v",OFFLINE)


if __name__ == "__main__":
    unittest.main()
