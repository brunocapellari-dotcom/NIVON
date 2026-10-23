"""Diagnóstico de ferramentas de engenharia NIVON, sem instalação/rede."""
from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys

REQUIRED = ("git", "claude", "codex", "docker")
OPTIONAL = ("gh", "ruff", "ty", "rg", "ast-grep", "sg", "serena", "codebase-memory-mcp", "rtk", "uv", "gitleaks", "semgrep", "osv-scanner", "ollama", "pytest")
CLAUDE_FLAGS = ("--restricted", "--bare", "--no-session-persistence", "--permission-prompts", "--tools")
CODEX_FLAGS = ("--sandbox", "--json")


def call(args):
    try:
        return subprocess.run(args, capture_output=True, text=True, timeout=15, check=False)
    except (OSError, subprocess.SubprocessError):
        return None


def doctor():
    found = {tool: bool(shutil.which(tool)) for tool in REQUIRED + OPTIONAL}
    flags = {}
    if found["claude"]:
        run = call(["claude", "--help"])
        desc = ((run.stdout or "") + "\n" + (run.stderr or "")) if run else ""
        flags["claude"] = {flag: flag in desc for flag in CLAUDE_FLAGS}
    if found["codex"]:
        run = call(["codex", "exec", "--help"])
        desc = ((run.stdout or "") + "\n" + (run.stderr or "")) if run else ""
        flags["codex"] = {flag: flag in desc for flag in CODEX_FLAGS}
    image = os.environ.get("NIVON_PYTHON_IMAGE", "python:3.11-slim")
    image_ok = bool(re.fullmatch(r"python:3\.11(?:-slim)?", image))
    local_image = False
    if found["docker"] and image_ok:
        result = call(["docker", "image", "inspect", image])
        local_image = bool(result and result.returncode == 0)
    return {
        "required": {k: found[k] for k in REQUIRED},
        "optional": {k: found[k] for k in OPTIONAL},
        "supported_flags": flags,
        "docker_image_local": local_image,
        "docker_image_allowed": image_ok,
        "ready_for_pilot": (
            all(found[x] for x in REQUIRED) and image_ok and local_image
            and all(all(v.values()) for v in flags.values())
        ),
        "local_model_option": ("ollama_available_manual_configuration"
                                if found.get("ollama") else "ollama_not_installed"),
        "limits": "Não verifica login, franquia da assinatura, VRAM/RAM, licenças de modelos, isolamento real do host ou cobrança.",
    }


def main(argv=None):
    parser = argparse.ArgumentParser(description="NIVON: diagnóstico local sem consumir tokens")
    parser.add_argument("command", choices=("doctor",))
    parser.parse_args(argv)
    result = doctor()
    print(json.dumps(result, indent=2, ensure_ascii=False))
    return 0 if result["ready_for_pilot"] else 2


if __name__ == "__main__":
    sys.exit(main())
