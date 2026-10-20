"""Regressões de CI: jobs de fontes reais nunca habilitados por padrão.

Não substitui aprovação jurídica, revisão de dados ou testes em nuvem.
"""
from pathlib import Path
import re
import unittest

ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github" / "workflows" / "testes.yml"

SOURCE_JOBS = {
    "conferir-schema-mapa": "NIVON_FONTE_MAPA_SIPEAGRO_HOMOLOGADA",
    "inspecao-conab-xls": "NIVON_FONTE_CONAB_XLS_HOMOLOGADA",
    "inspecao-antt-ferrovias": "NIVON_FONTE_ANTT_FERROVIAS_HOMOLOGADA",
    "inspecao-antt-csv-2026": "NIVON_FONTE_ANTT_CSV_HOMOLOGADA",
    "inspecao-anp-diesel": "NIVON_FONTE_ANP_DIESEL_HOMOLOGADA",
}


def corpo_job(yaml_text: str, job_id: str) -> str:
    found = re.search(r"(?m)^  " + re.escape(job_id) + r":\s*$", yaml_text)
    if found is None:
        raise ValueError("job de diagnóstico ausente: " + job_id)
    rest = yaml_text[found.end():]
    next_job = re.search(r"(?m)^  [a-z][a-z0-9-]*:\s*$", rest)
    return rest[:next_job.start()] if next_job else rest


class TestDiagnosticosFontesEmCI(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.raw = WORKFLOW.read_text(encoding="utf-8")

    def test_sem_eventos_privilegiados_ou_agendamento_de_fontes(self):
        self.assertNotIn("pull_request_target:", self.raw)
        self.assertNotRegex(self.raw, r"(?m)^  schedule:\s*$")
        self.assertRegex(self.raw, r"(?m)^permissions:\s*\n  contents: read\s*$")

    def test_opt_in_esta_desligado(self):
        block = re.search(
            r"(?ms)^  workflow_dispatch:\s*\n"
            r"    inputs:\s*\n"
            r"      confirmar_diagnostico_fonte_real:\s*\n"
            r"(.*?)(?=^permissions:)",
            self.raw,
        )
        self.assertIsNotNone(block, "input de homologação manual ausente")
        self.assertIn("required: true", block.group(1))
        self.assertIn("type: boolean", block.group(1))
        self.assertIn("default: false", block.group(1))

    def test_cada_fonte_exige_variavel_especifica_e_main(self):
        for job, flag in SOURCE_JOBS.items():
            with self.subTest(job=job):
                body = corpo_job(self.raw, job)
                self.assertIn("github.event_name == 'workflow_dispatch'", body)
                self.assertIn("github.ref == 'refs/heads/main'", body)
                self.assertIn("inputs.confirmar_diagnostico_fonte_real == true", body)
                self.assertIn("vars." + flag + " == 'true'", body)
                self.assertIn("if: >-", body)

    def test_isolamento_por_fonte_nao_aceita_flag_global(self):
        flags = set(SOURCE_JOBS.values())
        self.assertEqual(len(flags), len(SOURCE_JOBS))
        for job, own_flag in SOURCE_JOBS.items():
            body = corpo_job(self.raw, job)
            for other in flags - {own_flag}:
                self.assertNotIn("vars." + other, body)

    def test_actions_reutilizaveis_fixadas_por_sha(self):
        actions = re.findall(r"(?m)^\s*(?:-\s*)?uses:\s*([^\s#]+)", self.raw)
        self.assertTrue(actions)
        for action in actions:
            with self.subTest(action=action):
                self.assertRegex(action, r"^[A-Za-z0-9_./-]+@[0-9a-f]{40}$")
        self.assertNotIn("persist-credentials: true", self.raw)
        self.assertIn("persist-credentials: false", self.raw)


if __name__ == "__main__":
    unittest.main()
