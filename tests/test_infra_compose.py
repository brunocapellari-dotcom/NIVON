"""Guardrails de container offline: sem rede, portas, segredos ou deploy."""
from pathlib import Path
import shutil
import subprocess
import unittest

ROOT = Path(__file__).resolve().parents[1]


class AuditContainerTests(unittest.TestCase):
    def test_compose_e_explicitamente_offline(self):
        raw = (ROOT / "infra/compose.yaml").read_text(encoding="utf-8")
        for directive in (
            'profiles: ["audit"]', 'network_mode: "none"',
            "read_only: true", "no-new-privileges:true",
            "pids_limit:", "cap_drop:", 'restart: "no"',
        ):
            self.assertIn(directive, raw)
        for forbidden in ("privileged: true", "ports:", "network_mode: host",
                          "docker.sock", "secrets:", "volumes:"):
            self.assertNotIn(forbidden, raw)

    def test_imagem_execucao_sem_privilegios(self):
        dockerfile = (ROOT / "infra/docker/Dockerfile.audit").read_text(encoding="utf-8")
        self.assertIn("USER 65532:65532", dockerfile)
        self.assertIn("PYTHONPATH=/app/src", dockerfile)
        self.assertNotIn("COPY . ", dockerfile)
        self.assertNotIn("EXPOSE ", dockerfile)
        self.assertNotIn("RUN curl", dockerfile)

    def test_dockerignore_exclui_segredos(self):
        rules = (ROOT / ".dockerignore").read_text(encoding="utf-8")
        for pattern in ("*", "!src/", "!config/", "**/*.pem", "**/.env*", "**/*.sqlite*"):
            self.assertIn(pattern, rules)

    def test_compose_valido_quando_disponivel(self):
        binary = shutil.which("docker")
        if not binary:
            self.skipTest("docker não instalado; schema Compose aguarda CI Docker")
        try:
            version = subprocess.run([binary, "compose", "version"], capture_output=True,
                                     text=True, timeout=12, check=False)
        except (OSError, subprocess.TimeoutExpired) as exc:
            # A sondagem opcional não pode derrubar a suíte de código quando
            # o Docker do runner está travado; registrar SKIPPED, nunca PASS.
            self.skipTest("docker compose não responsivo/indisponível: " + str(exc))
        if version.returncode:
            self.skipTest("docker compose plugin não disponível")
        try:
            parsed = subprocess.run(
                [binary, "compose", "-f", str(ROOT / "infra/compose.yaml"),
                 "--profile", "audit", "config", "--quiet"],
                capture_output=True, text=True, timeout=20, check=False,
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            self.skipTest("diagnóstico Compose indisponível: " + str(exc))
        self.assertEqual(parsed.returncode, 0, parsed.stderr)


if __name__ == "__main__":
    unittest.main()
