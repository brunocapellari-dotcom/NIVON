"""Homologação EXPLORATÓRIA de wheels para Alpine/musl (sem release).

Fase download permite apenas wheels do índice público PyPI; fase smoke roda
totalmente offline com as wheels baixadas. O projeto NIVON não é instalado
nem os coletores executados. Depêndencias opcionais permanecem não aprovadas.
"""
from __future__ import annotations

import argparse
import json
import os
import re
from pathlib import Path
import subprocess
import sys
import tomllib

from .infra_supplychain import ErroSupplyChain

EXPECTED = {
    "agro": ("agrobr==2.0.0",),
    "forecast": ("pandas>=2.2,<3", "statsforecast>=2,<3"),
    "ports": ("pdfplumber>=0.11,<1",),
    "excel": ("openpyxl>=3.1,<4",),
}
SMOKES = {
    "agro": "import agrobr; assert agrobr is not None",
    "forecast": "import pandas; from statsforecast import StatsForecast; assert pandas.__version__",
    "ports": "import pdfplumber; assert callable(pdfplumber.open)",
    "excel": "import io,openpyxl; w=openpyxl.Workbook(); w.active['A1']='nivon'; out=io.BytesIO(); w.save(out); assert out.getbuffer().nbytes>0",
}
IMAGE = "python:3.11.17-alpine3.23@sha256:924d53e01cee5204d35fbcfb71b6c1568c857d7c31141f960ff6a37e111ecc7f"
DEBIAN_IMAGE = "python:3.11-slim-trixie@sha256:cce12316475d7d56d605f76e1d811d0dc4e7227f2d4afd29951521264f504ff8"
DISTROS = {"alpine": IMAGE, "debian": DEBIAN_IMAGE}
MAX_WHEELS = 220
MAX_WHEEL_BYTES = 400_000_000


def requirements(path: str | Path, group: str) -> tuple[str, ...]:
    if group not in EXPECTED:
        raise ErroSupplyChain("grupo opcional não homologado")
    f = Path(path)
    if f.is_symlink() or not f.is_file() or f.stat().st_size > 500_000:
        raise ErroSupplyChain("pyproject inválido")
    try:
        with f.open("rb") as fp:
            data = tomllib.load(fp)
    except (OSError, ValueError, tomllib.TOMLDecodeError) as exc:
        raise ErroSupplyChain("pyproject não pôde ser interpretado") from exc
    project = data.get("project", {})
    if not isinstance(project, dict) or project.get("dependencies") != []:
        raise ErroSupplyChain("dependências obrigatórias alteradas sem revisão")
    opt = project.get("optional-dependencies")
    if not isinstance(opt, dict) or set(opt) != set(EXPECTED):
        raise ErroSupplyChain("grupos opcionais divergem do contrato")
    for name, wanted in EXPECTED.items():
        if not isinstance(opt[name], list) or tuple(opt[name]) != wanted:
            raise ErroSupplyChain("versão/restrição mudou e exige revisão")
    return EXPECTED[group]


def _files(folder: Path) -> tuple[int, int]:
    if folder.is_symlink() or not folder.is_dir():
        raise ErroSupplyChain("pasta de wheels inválida")
    entries = tuple(folder.iterdir())
    if not entries or len(entries) > MAX_WHEELS:
        raise ErroSupplyChain("quantidade de wheels inválida")
    total = 0
    for f in entries:
        if f.is_symlink() or not f.is_file() or f.suffix != ".whl":
            raise ErroSupplyChain("wheelhouse contém arquivo não permitido")
        total += f.stat().st_size
        if total > MAX_WHEEL_BYTES:
            raise ErroSupplyChain("wheelhouse acima do limite")
    return len(entries), total


def _resumir_falha(stderr: str) -> str:
    """Classificar mensagens pip sem devolver URLs, caminhos ou logs brutos."""
    if not isinstance(stderr, str):
        return "resolução ou execução falhou; causa indeterminada"
    missing = re.findall(
        r"No matching distribution found for ([A-Za-z0-9][A-Za-z0-9._+-]{0,80})",
        stderr, flags=re.IGNORECASE,
    )
    if missing:
        return "wheel indisponível para requisito público: " + missing[-1]
    if ("Could not find a version that satisfies the requirement" in stderr
            or "no matching distribution" in stderr.lower()):
        return "versão de wheel ausente ou restrições conflitantes"
    native_lib = re.findall(
        r"([A-Za-z0-9_+.-]+\.so(?:\.[0-9]+)*)[: ]+cannot open shared object",
        stderr, flags=re.IGNORECASE,
    )
    if native_lib:
        return "biblioteca nativa ausente no container: " + native_lib[-1]
    module_name = re.findall(
        r"ModuleNotFoundError: No module named ['\\\"]([A-Za-z0-9_.]{1,80})['\\\"]",
        stderr,
    )
    if module_name:
        return "módulo Python não importável: " + module_name[-1]
    if "no space left on device" in stderr.lower() or "errno 28" in stderr.lower():
        return "volume temporário sem espaço; aumentar somente cota de ensaio"
    if "permission denied" in stderr.lower() or "errno 13" in stderr.lower():
        return "permissão insuficiente no contêiner efêmero"
    if ("externally-managed-environment" in stderr.lower()
            or "this environment is externally managed" in stderr.lower()):
        return "política de instalação do Python impede destino"
    if ("cannot install" in stderr.lower() or "resolutionimpossible" in stderr.lower()
            or "conflicting dependencies" in stderr.lower()):
        return "conflito de versões na instalação offline"
    if "invalid wheel" in stderr.lower() or "not a supported wheel" in stderr.lower():
        return "arquivo wheel ou ABI incompatível"
    if "symbol not found" in stderr.lower() or "undefined symbol" in stderr.lower():
        return "incompatibilidade de símbolo ou biblioteca nativa"
    if "importerror" in stderr.lower():
        return "falha de importação (ImportError)"
    if "permissionerror" in stderr.lower():
        return "bloqueio de permissão no ambiente isolado"
    if any(term in stderr.lower() for term in (
        "temporary failure in name resolution", "name or service not known",
        "connection refused", "read timed out", "ssl:", "certificate verify failed",
        "proxyerror", "too many 429 error responses",
    )):
        return "falha de rede/TLS/índice PyPI; não inferir ausência de wheel"
    return "resolução ou execução falhou; causa indeterminada"


def _subprocess(argv: list[str], *, timeout: int, env: dict[str, str] | None = None, stage: str = "UNKNOWN") -> None:
    try:
        r = subprocess.run(argv, check=False, timeout=timeout,
                           stdout=subprocess.DEVNULL, stderr=subprocess.PIPE,
                           text=True, errors="replace", env=env)
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise ErroSupplyChain(stage + ": comando isolado indisponível ou excedeu limite") from exc
    if r.returncode:
        raise ErroSupplyChain(stage + ": " + _resumir_falha(r.stderr))


def executar(group: str, phase: str, *, pyproject: str, root: str,
             distro: str = "alpine") -> dict:
    specs = requirements(pyproject, group)
    if distro not in DISTROS:
        raise ErroSupplyChain("distribuição não autorizada")
    try:
        release = Path("/etc/os-release").read_text(encoding="utf-8")
    except (OSError, UnicodeError) as exc:
        raise ErroSupplyChain("identidade do SO não verificada") from exc
    os_id = next((line.removeprefix("ID=").strip().strip('"')
                  for line in release.splitlines() if line.startswith("ID=")), None)
    if os_id != distro:
        raise ErroSupplyChain("imagem-base não corresponde à distribuição declarada")
    if phase not in ("download", "offline"):
        raise ErroSupplyChain("fase não autorizada")
    base = Path(root)
    if base.is_symlink() or not base.is_dir() or base.resolve() != Path("/var/nivon-wheels"):
        raise ErroSupplyChain("diretório temporário não permitido")
    wheels = base / group / "wheels"
    site = base / group / "site"
    if phase == "download":
        if (base / group).is_symlink() or wheels.is_symlink() or wheels.exists():
            raise ErroSupplyChain("diretório de download deve começar vazio")
        wheels.mkdir(parents=True, mode=0o700)
        command = [sys.executable, "-m", "pip", "download", "--only-binary=:all:",
                   "--no-cache-dir", "--disable-pip-version-check", "--no-input",
                   "--index-url", "https://pypi.org/simple", "--dest", str(wheels),
                   *specs]
        env = dict(os.environ)
        env["PIP_EXTRA_INDEX_URL"] = ""
        env["PIP_CONFIG_FILE"] = os.devnull
        _subprocess(command, timeout=190, env=env, stage="WHEEL_DOWNLOAD")
    else:
        count, size = _files(wheels)
        if site.exists() or site.is_symlink():
            raise ErroSupplyChain("diretório de instalação deve começar vazio")
        site.mkdir(mode=0o700)
        command = [sys.executable, "-m", "pip", "install", "--no-index", "--only-binary=:all:",
                   "--no-cache-dir", "--no-compile", "--no-input", "--find-links", str(wheels),
                   "--target", str(site), *specs]
        env = dict(os.environ)
        env["PIP_CONFIG_FILE"] = os.devnull
        env["PIP_EXTRA_INDEX_URL"] = ""
        _subprocess(command, timeout=160, env=env, stage="OFFLINE_INSTALL")
        script = "import site,sys; site.addsitedir(sys.argv[1]); " + SMOKES[group]
        _subprocess([sys.executable, "-I", "-c", script, str(site)], timeout=80,
                    env=env, stage="OFFLINE_IMPORT")
    count, size = _files(wheels)
    return {
        "schema": "nivon.infrastructure.optional_wheels.v1",
        "group": group,
        "phase": phase,
        "distro": distro,
        "image_base_pinned": DISTROS[distro],
        "libc_family": "musl" if distro == "alpine" else "glibc",
        "wheel_count": count,
        "wheels_bytes": size,
        "resolver": "PyPI only / binary wheels" if phase == "download" else "offline-only",
        "native_musl_dependencies_probed": phase == "offline" and distro == "alpine",
        "collector_network_called": False,
        "release_authorized": False,
        "runtime_image_changed": False,
        "transitive_versions_locked_for_release": False,
    }


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Auditoria de rodas binárias opcionais sem deploy")
    p.add_argument("--group", required=True, choices=tuple(EXPECTED))
    p.add_argument("--distro", required=True, choices=tuple(DISTROS))
    p.add_argument("--phase", required=True, choices=("download", "offline"))
    p.add_argument("--pyproject", default="/workspace/pyproject.toml")
    p.add_argument("--root", default="/var/nivon-wheels")
    args = p.parse_args(argv)
    try:
        result = executar(args.group, args.phase, pyproject=args.pyproject,
                          root=args.root, distro=args.distro)
    except (OSError, ValueError) as exc:
        print(json.dumps({"schema": "nivon.infrastructure.optional_wheels.v1",
                          "group": args.group, "phase": args.phase, "distro": args.distro,
                          "status": "BLOCKED", "reason": str(exc),
                          "release_authorized": False}, sort_keys=True))
        return 2
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
