"""Testes de contrato sem rede para resolução isolada de wheels na Alpine."""
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch
import json
import subprocess
import unittest

from nivon.infra_optional_wheels import EXPECTED, SMOKES, IMAGE, requirements, _subprocess, _files
from nivon.infra_supplychain import ErroSupplyChain

ROOT = Path(__file__).resolve().parents[1]


class TestOptionalWheels(unittest.TestCase):
    def test_pyproject_real_possui_quatro_extras_esperados(self):
        for group in EXPECTED:
            self.assertEqual(requirements(ROOT / "pyproject.toml", group), EXPECTED[group])
            self.assertIn(group, SMOKES)
        with self.assertRaises(ErroSupplyChain):
            requirements(ROOT / "pyproject.toml", "invalid")

    def test_modificacao_do_grupo_impede_execucao_automatica(self):
        original = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
        with TemporaryDirectory() as d:
            p = Path(d) / "pyproject.toml"
            p.write_text(original.replace("agrobr==2.0.0", "agrobr>=2.0"),
                         encoding="utf-8")
            with self.assertRaises(ErroSupplyChain):
                requirements(p, "agro")
            p.write_text(original.replace("dependencies = []", 'dependencies = ["requests"]'),
                         encoding="utf-8")
            with self.assertRaises(ErroSupplyChain):
                requirements(p, "agro")

    def test_wheelhouse_nao_aceita_fonte_ou_arquivos_vazios(self):
        with TemporaryDirectory() as d:
            path = Path(d)
            with self.assertRaises(ErroSupplyChain):
                _files(path)
            (path / "src.tar.gz").write_bytes(b"placeholder")
            with self.assertRaises(ErroSupplyChain):
                _files(path)
            (path / "src.tar.gz").unlink()
            (path / "test-1-py3-none-any.whl").write_bytes(b"synthetic")
            self.assertEqual(_files(path), (1, 9))

    def test_download_falha_nao_oculta_erros_ou_stdout(self):
        with patch("nivon.infra_optional_wheels.subprocess.run") as run:
            run.return_value.returncode = 1
            with self.assertRaises(ErroSupplyChain):
                _subprocess(["python", "-m", "pip"], timeout=30)
            self.assertEqual(run.call_args.kwargs["stdout"], subprocess.DEVNULL)
            self.assertEqual(run.call_args.kwargs["stderr"], subprocess.DEVNULL)

    def test_timeout_fecha_execucao(self):
        with patch("nivon.infra_optional_wheels.subprocess.run",
                   side_effect=subprocess.TimeoutExpired("pip", 10)):
            with self.assertRaises(ErroSupplyChain):
                _subprocess(["python", "-m", "pip"], timeout=10)

    def test_workflow_nao_usa_imagem_nao_pinnada_ou_sdist(self):
        wf = (ROOT / ".github/workflows/infra_optional_wheels.yml").read_text(encoding="utf-8")
        self.assertIn(IMAGE, wf)
        for phrase in ("ubuntu-24.04-arm", "ubuntu-latest",
                       "--only-binary=:all:", "--phase download",
                       "--phase offline", "--network none", "https://pypi.org/simple",
                       "persist-credentials: false", "--cap-drop ALL", "--read-only",
                       "MAX-WHEEL-DEPENDENCY-GATE"):
            self.assertIn(phrase, wf)
        for forbidden in ("docker push", "docker login", "secrets.",
                          "upload-artifact@", "pull_request_target:",
                          "continue-on-error: true", "pip install --upgrade"):
            self.assertNotIn(forbidden, wf)
        self.assertIn("contents: read", wf)
        self.assertIn('test "$host_arch" = "$ARCH"', wf)


if __name__ == "__main__":
    unittest.main()
