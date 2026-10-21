"""Auditoria independente, read-only, dos workflows privados NIVON.

Nenhum secret, environment real, request, token ou runner remoto é acessado.
O objetivo é impedir que YAML de verificação privada seja aceito como
homologado quando o GitHub rejeita a construção de jobs.
"""
from __future__ import annotations

from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]
MANUAL = ROOT / ".github" / "workflows" / "acessos-privados.yml"
WORKFLOW_OFFLINE = ROOT / ".github" / "workflows" / "testes-acessos-isolados.yml"


class TestAuditoriaAcessosPrivadosWorkflow(unittest.TestCase):
    def test_controle_sem_disparo_live_em_pull_request(self):
        source = MANUAL.read_text(encoding="utf-8")
        triggers = source.split("\non:", 1)[1].split("\npermissions:", 1)[0]
        self.assertIn("workflow_dispatch:", triggers)
        for forbidden in ("pull_request:", "pull_request_target:", "push:",
                          "schedule:", "workflow_run:"):
            self.assertNotIn(forbidden, triggers)
        self.assertEqual(source.count("github.ref == 'refs/heads/main'"), 3)
        self.assertEqual(source.count("environment: nivon-fontes-privadas"), 3)

    def test_p0_runner_contexto_nao_e_permitido_no_env_do_job(self):
        # O GitHub suporta `runner.temp` em steps.env, mas não em jobs.<id>.env.
        # Escopo de YAML: indentação 6 para variável de job; indentação 10
        # para a mesma variável de step. Não depende de biblioteca YAML.
        source = MANUAL.read_text(encoding="utf-8")
        expr = "$" + "{{ runner.temp }}"
        invalidos = []
        for number, line in enumerate(source.splitlines(), start=1):
            stripped = line.lstrip(" ")
            if "runner." in stripped and expr not in stripped:
                # Nada a certificar sobre outras formas, mas as expressões
                # de `runner.*` são todas de step scope.
                pass
            if expr in line and (len(line) - len(stripped)) < 10:
                invalidos.append(number)
        self.assertFalse(
            invalidos,
            "P0: referencia runner.temp em jobs.env (fora do contexto "
            "GitHub permitido), linhas " + str(invalidos) +
            "; workflow_dispatch pode falhar antes de criar jobs",
        )

    def test_p1_diretorio_privado_inmet_disponivel_no_step_que_recebe_zip(self):
        source = MANUAL.read_text(encoding="utf-8")
        var = "NIVON_INMET_DIRETORIO_PRIVADO: " + "$" + "{{ runner.temp }}/nivon-bdmep"
        # Criação da pasta e o processo que usa o ZIP precisam receber
        # o MESMO caminho; contexto runner.temp só está disponível em steps.
        step_scope_count = sum(
            (len(line) - len(line.lstrip(" "))) >= 10 and line.strip() == var
            for line in source.splitlines()
        )
        self.assertGreaterEqual(
            step_scope_count, 2,
            "P1: pasta privada precisa ser passada nos dois steps do "
            "INMET, no escopo correto, antes de acesso live",
        )

    def test_controle_suite_offline_sem_acesso_a_segredos(self):
        manual = MANUAL.read_text(encoding="utf-8")
        offline = WORKFLOW_OFFLINE.read_text(encoding="utf-8")
        self.assertIn("default: preflight", manual)
        self.assertIn("--preflight", manual)
        self.assertEqual(manual.count('elif [ "$NIVON_ACCESS_MODE" = "live" ]; then'), 3)
        self.assertIn("pull_request:", offline)
        self.assertNotIn("secrets.", offline)
        self.assertNotIn(" --live", offline)


if __name__ == "__main__":
    unittest.main()
