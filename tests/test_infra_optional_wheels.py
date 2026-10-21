"""Testes de contrato sem rede para resolução isolada de wheels na Alpine."""
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch
import json
import subprocess
import unittest

from nivon.infra_optional_wheels import EXPECTED, SMOKES, IMAGE, DEBIAN_IMAGE, DISTROS, executar, requirements, _subprocess, _files, _resumir_falha
from nivon.infra_supplychain import ErroSupplyChain

ROOT = Path(__file__).resolve().parents[1]


class TestOptionalWheels(unittest.TestCase):
    def test_imagens_pinnadas_e_identidade_distinta(self):
        self.assertEqual(set(DISTROS), {"alpine", "debian"})
        self.assertIn("@sha256:", IMAGE)
        self.assertIn("@sha256:", DEBIAN_IMAGE)
        self.assertNotEqual(IMAGE, DEBIAN_IMAGE)
        self.assertNotIn("alpine", DEBIAN_IMAGE)

    def test_falsa_identidade_de_distribuicao_bloqueada(self):
        with self.assertRaises(ErroSupplyChain):
            executar("agro", "download", pyproject=str(ROOT / "pyproject.toml"),
                     root="/var/nivon-wheels", distro="fake-os")

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
            run.return_value.stderr = "private path /token?secret=abc"
            with self.assertRaises(ErroSupplyChain):
                _subprocess(["python", "-m", "pip"], timeout=30)
            self.assertEqual(run.call_args.kwargs["stdout"], subprocess.DEVNULL)
            self.assertEqual(run.call_args.kwargs["stderr"], subprocess.PIPE)
            self.assertNotIn("secret=abc", _resumir_falha(run.return_value.stderr))

    def test_diagnostico_wheel_ausente_sem_vazar_log_pip(self):
        raw = "ERROR: Could not find a version that satisfies the requirement llvmlite\\nERROR: No matching distribution found for llvmlite"
        summary = _resumir_falha(raw)
        self.assertIn("llvmlite", summary)
        self.assertNotIn("ERROR:", summary)
        self.assertNotIn("Could not find", summary)
        self.assertEqual(_resumir_falha("Connection refused by gateway"), "falha de rede/TLS/índice PyPI; não inferir ausência de wheel")
        self.assertEqual(_resumir_falha("a /tmp/private/token"), "resolução ou execução falhou; causa indeterminada")

    def test_falha_offline_distingue_instalacao_e_importacao(self):
        with patch("nivon.infra_optional_wheels.subprocess.run") as run:
            run.return_value.returncode = 1
            run.return_value.stderr = "ImportError: libgomp.so.1: cannot open shared object file: No such file or directory"
            with self.assertRaises(ErroSupplyChain) as cm:
                _subprocess(["python", "-I"], timeout=30, stage="OFFLINE_IMPORT")
            self.assertIn("OFFLINE_IMPORT", str(cm.exception))
            self.assertIn("libgomp.so.1", str(cm.exception))
            self.assertNotIn("No such file or directory", str(cm.exception))
            run.return_value.stderr = "ERROR: PermissionError: /private/sensitive/path"
            with self.assertRaises(ErroSupplyChain) as install:
                _subprocess(["python", "-m", "pip"], timeout=30, stage="OFFLINE_INSTALL")
            self.assertIn("OFFLINE_INSTALL", str(install.exception))
            self.assertNotIn("sensitive", str(install.exception))

    def test_espaco_temporario_sem_expor_caminhos(self):
        self.assertEqual(_resumir_falha("OSError: [Errno 28] No space left on device at /private/path"),
                         "volume temporário sem espaço; aumentar somente cota de ensaio")
        self.assertEqual(_resumir_falha("ERROR: Cannot install X and Y because these packages have conflicting dependencies."),
                         "conflito de versões na instalação offline")
        self.assertEqual(_resumir_falha("ERROR: [Errno 13] Permission denied: /private/path"),
                         "permissão insuficiente no contêiner efêmero")

    def test_timeout_fecha_execucao(self):
        with patch("nivon.infra_optional_wheels.subprocess.run",
                   side_effect=subprocess.TimeoutExpired("pip", 10)):
            with self.assertRaises(ErroSupplyChain):
                _subprocess(["python", "-m", "pip"], timeout=10)

    def test_workflow_nao_usa_imagem_nao_pinnada_ou_sdist(self):
        wf = (ROOT / ".github/workflows/infra_optional_wheels.yml").read_text(encoding="utf-8")
        self.assertIn(IMAGE, wf)
        self.assertIn(DEBIAN_IMAGE, wf)
        self.assertIn("--distro", wf)
        self.assertIn("size=1024m,uid=65532,gid=65532", wf)
        self.assertIn("distro: debian", wf)
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
