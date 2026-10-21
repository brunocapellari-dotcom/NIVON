"""Guarda de CI: testes sintéticos automáticos; redes externas só opt-in."""
import re
import unittest
from pathlib import Path

CAMINHO=Path(__file__).resolve().parents[1]/".github/workflows/testes.yml"
EXTERNOS=("conferir-schema-mapa","inspecao-conab-xls",
          "inspecao-antt-ferrovias","inspecao-antt-csv-2026",
          "inspecao-anp-diesel")

class TestWorkflowNetworkSafety(unittest.TestCase):
    def test_jobs_externos_nao_rodar_em_pr(self):
        conteudo=CAMINHO.read_text(encoding="utf-8")
        for nome in EXTERNOS:
            bloco="  "+nome+":"
            self.assertIn(bloco,conteudo)
            match=re.search(r"(?m)^  "+re.escape(nome)+r":\s*\n" +
                            r"([\s\S]*?)(?=^  [A-Za-z0-9_-]+:\s*$|\Z)",conteudo)
            self.assertIsNotNone(match)
            resto=match.group(1)
            self.assertIn("if: github.event_name == 'workflow_dispatch'",resto,
                msg=f"{nome} deve requerer disparo manual")

    def test_validacao_offline_continua_em_pr(self):
        conteudo=CAMINHO.read_text(encoding="utf-8")
        p=conteudo.index("  validar-nucleo:")
        q=conteudo.find("\n  conferir-schema-mapa:",p)
        parte=conteudo[p:q]
        self.assertNotIn("if: github.event_name == 'workflow_dispatch'",parte)
        self.assertIn("python -m unittest discover -s tests -v",parte)

    def test_sem_agendamento_ou_execucao_push(self):
        conteudo=CAMINHO.read_text(encoding="utf-8")
        self.assertNotIn("  schedule:",conteudo)
        self.assertNotIn("  push:",conteudo)

class TestWorkflowPrivateSourceSafety(unittest.TestCase):
    """Workflow com secrets só pode ser usado manualmente na main."""

    def setUp(self):
        self.workflow = (CAMINHO.parent / "acessos-privados.yml").read_text(encoding="utf-8")

    def test_somente_workflow_dispatch(self):
        triggers = self.workflow.split("on:", 1)[1].split("permissions:", 1)[0]
        self.assertIn("workflow_dispatch:", triggers)
        for forbidden in ("pull_request:", "pull_request_target:", "push:",
                          "schedule:", "workflow_run:", "repository_dispatch:"):
            self.assertNotIn(forbidden, triggers)

    def test_exige_main_e_ambiente_privado(self):
        self.assertEqual(self.workflow.count("environment: nivon-fontes-privadas"), 3)
        for fonte in ("usda", "ana", "inmet"):
            self.assertIn(
                "if: github.event_name == 'workflow_dispatch' && "
                "github.ref == 'refs/heads/main' && inputs.fonte == '" + fonte + "'",
                self.workflow,
            )
        self.assertIn("  contents: read", self.workflow)
        self.assertNotIn("contents: write", self.workflow)

    def test_segredos_separados(self):
        blocks = {}
        for fonte in ("usda", "ana", "inmet"):
            start = self.workflow.index("  validar-" + fonte + ":")
            end = self.workflow.find("\n  validar-", start + 1)
            blocks[fonte] = self.workflow[start:end if end >= 0 else None]
        self.assertIn("secrets.AGROBR_USDA_API_KEY", blocks["usda"])
        self.assertIn("secrets.NIVON_ANA_SENHA", blocks["ana"])
        self.assertIn("secrets.NIVON_INMET_BDMEP_URL", blocks["inmet"])
        self.assertNotIn("secrets.NIVON_ANA_SENHA", blocks["usda"])
        self.assertNotIn("secrets.NIVON_INMET_BDMEP_URL", blocks["usda"])
        self.assertNotIn("secrets.AGROBR_USDA_API_KEY", blocks["ana"])
        self.assertNotIn("secrets.NIVON_INMET_BDMEP_URL", blocks["ana"])
        self.assertNotIn("secrets.AGROBR_USDA_API_KEY", blocks["inmet"])
        self.assertNotIn("secrets.NIVON_ANA_SENHA", blocks["inmet"])

    def test_sem_upload_ou_echo_de_credenciais(self):
        for forbidden in ("actions/upload-artifact", "echo $", "printenv",
                          "set -x", "pip install", "curl ", "wget ", "schedule:"):
            self.assertNotIn(forbidden, self.workflow)
        self.assertIn('run: mkdir -m 700 "$NIVON_INMET_DIRETORIO_PRIVADO"', self.workflow)
        self.assertIn("timeout-minutes: 4", self.workflow)
