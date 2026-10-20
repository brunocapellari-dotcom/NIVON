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
            self.assertRegex(resto,r"(?m)^    if: >-\s*$",
                msg=f"{nome} deve ter condicao explicita de job")
            self.assertIn("github.event_name == 'workflow_dispatch'",resto,
                msg=f"{nome} deve requerer disparo manual")
            self.assertIn("github.ref == 'refs/heads/main'",resto)
            self.assertIn("inputs.confirmar_diagnostico_fonte_real == true",resto)
            self.assertRegex(resto,r"vars\.NIVON_FONTE_[A-Z_]+_HOMOLOGADA == 'true'")

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
