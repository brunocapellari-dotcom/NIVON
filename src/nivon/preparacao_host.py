"""Pré-homologação do host NIVON, com modelos desligados.

O teste usa apenas código local e uma imagem Docker previamente instalada.
Não efetua pull/build, não lê tokens e não executa Claude ou Codex.
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import re
import subprocess
import sys

from nivon.ferramentas import doctor, APPROVED_IMAGES
from nivon.token_guard import summarize

ROOT = Path(__file__).resolve().parents[2]
DOCKER_IMAGES = APPROVED_IMAGES
RE_TEST_COUNT = re.compile(r"Ran\s+(\d+)\s+tests?")
RE_SKIPPED = re.compile(r"skipped=(\d+)")


def sandbox_arguments(root=ROOT, image=None):
    image = image or os.environ.get("NIVON_PYTHON_IMAGE", "python:3.11-slim")
    if image not in DOCKER_IMAGES:
        raise ValueError("Imagem fora da lista homologável")
    root = Path(root).resolve(strict=True)
    if not root.is_dir() or not (root / "src" / "nivon").is_dir():
        raise ValueError("Não é o checkout NIVON")
    args = [
        "docker", "run", "--rm", "--pull", "never",
        "--network", "none", "--cap-drop", "ALL",
        "--security-opt", "no-new-privileges",
        "--pids-limit", "128", "--memory", "512m", "--cpus", "1",
        "--read-only", "--tmpfs", "/tmp:rw,noexec,nosuid,size=64m",
        "--mount", f"type=bind,src={root},dst=/workspace,readonly",
        "--workdir", "/workspace", "--env", "PYTHONPATH=/workspace/src",
        "--env", "PYTHONDONTWRITEBYTECODE=1",
    ]
    if hasattr(os, "getuid") and hasattr(os, "getgid"):
        args += ["--user", f"{os.getuid()}:{os.getgid()}"]
    return args + [image]


def smoke(*, root=ROOT, image=None, allow_skips=False):
    """Prove the very same image can import project code and run its tests offline."""
    args = sandbox_arguments(root, image=image)
    checks = [
        args + ["python", "-m", "nivon.qualidade", "--json"],
        args + ["python", "-m", "unittest", "discover", "-s", "tests", "-q"],
    ]
    tested = 0
    skipped = 0
    reports = []
    for cmd in checks:
        try:
            result = subprocess.run(cmd, cwd=str(root), capture_output=True, text=True,
                                    check=False, timeout=240)
        except (OSError, subprocess.SubprocessError) as exc:
            return {"ready": False, "reason": type(exc).__name__,
                    "tests": tested, "skipped": skipped}
        text = result.stdout + "\n" + result.stderr
        sample = summarize(text, max_chars=1300)
        reports.append({"check": "AST" if len(reports) == 0 else "unittest",
                        "exit_code": result.returncode, "excerpt": sample})
        match = RE_TEST_COUNT.search(text)
        if match:
            tested = int(match.group(1))
        skip = RE_SKIPPED.search(text)
        if skip:
            skipped = int(skip.group(1))
        if result.returncode != 0:
            return {"ready": False, "reason": "test_failure",
                    "tests": tested, "skipped": skipped, "checks": reports}
    if skipped and not allow_skips:
        return {"ready": False, "reason": "optional_tests_skipped",
                "tests": tested, "skipped": skipped, "checks": reports}
    if tested == 0:
        return {"ready": False, "reason": "no_tests_observed",
                "tests": 0, "skipped": skipped, "checks": reports}
    return {"ready": True, "tests": tested, "skipped": skipped, "checks": reports}


def readiness(*, root=ROOT, image=None, allow_skips=False):
    target = image or os.environ.get("NIVON_PYTHON_IMAGE", "python:3.11-slim")
    host = doctor(image=target)
    output = {
        "host": host,
        "docker_smoke": None,
        "ready_for_night_pilot": False,
        "requires_local_operator": True,
        "provider_calls_made": 0,
        "actions": [],
    }
    if image is not None and image not in DOCKER_IMAGES:
        output["actions"].append("Escolha imagem previamente homologada.")
        return output
    if not host["supported_host"]:
        output["actions"].append("Usar Linux ou WSL2; execução Windows nativa bloqueada.")
    if not host["authentication"].get("claude") == "subscription":
        output["actions"].append("Confirmar login de assinatura Claude Code no host.")
    if not host["authentication"].get("codex") == "subscription":
        output["actions"].append("Confirmar login ChatGPT no Codex CLI no host.")
    if not host["docker_image_local"]:
        output["actions"].append("Preparar manualmente a imagem Docker e executar novamente.")
    if host["ready_for_pilot"]:
        output["docker_smoke"] = smoke(root=root, image=target, allow_skips=allow_skips)
        if output["docker_smoke"].get("reason") == "optional_tests_skipped":
            output["actions"].append("Imagem não cobre testes opcionais; usar nivon-agentes:test-py311 com PyArrow.")
        if output["docker_smoke"].get("ready"):
            output["ready_for_night_pilot"] = True
    return output


def main(argv=None):
    parser = argparse.ArgumentParser(description="Pré-homologação local, sem consumo de tokens de IA")
    parser.add_argument("command", choices=["check"])
    parser.add_argument("--image", choices=sorted(DOCKER_IMAGES))
    parser.add_argument("--allow-skips", action="store_true")
    args = parser.parse_args(argv)
    data = readiness(image=args.image, allow_skips=args.allow_skips)
    print(json.dumps(data, indent=2, ensure_ascii=False))
    return 0 if data["ready_for_night_pilot"] else 2


if __name__ == "__main__":
    sys.exit(main())
