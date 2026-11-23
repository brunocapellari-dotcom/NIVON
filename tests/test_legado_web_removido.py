"""Regressão da retirada do web público, sem eliminar o terminal privado."""
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]
LEGADO = (
    "api", "apps", "public", "vercel.json",
    ".github/workflows/ci-terminal-web.yml",
    ".github/workflows/mercado-portal-ci.yml",
    ".github/workflows/nivon-terminal-ci.yml",
    ".github/workflows/portal-cloudrun-privado.yml",
    ".github/workflows/portal-interno-ci.yml",
    ".github/workflows/portal-interno-gcp.yml",
    "tests/terminal_publico.test.js",
    "tests/test_terminal_publico.py",
    "tests_web/mercado_portal.test.cjs",
    "tests/test_portal_deploy_policy.py",
)

class TestRetiradaLegadoWeb(unittest.TestCase):
    def test_legado_removido(self):
        for item in LEGADO:
            with self.subTest(path=item):
                self.assertFalse((ROOT / item).exists())

    def test_terminal_cloud_run_e_interface_privada_preservados(self):
        for item in (
            "src/nivon/terminal_web.py",
            "src/nivon/portal_static/index.html",
            "src/nivon/portal_static/portal.css",
            "src/nivon/portal_static/portal.js",
            "infra/google_cloud/Dockerfile.terminal",
            ".github/workflows/nivon-terminal-go-live.yml",
        ):
            with self.subTest(path=item):
                self.assertTrue((ROOT / item).is_file())

    def test_base_privada_legivel_no_celular(self):
        pagina=(ROOT / "src/nivon/portal_static/index.html").read_text(encoding="utf-8")
        css=(ROOT / "src/nivon/portal_static/portal.css").read_text(encoding="utf-8")
        self.assertIn("width=device-width", pagina)
        self.assertIn("@media", css)

if __name__ == "__main__":
    unittest.main()
