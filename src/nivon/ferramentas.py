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
CLAUDE_FLAGS = ("--restricted", "--safe-mode", "--no-session-persistence", "--permission-prompts", "--tools")
CODEX_FLAGS = ("--sandbox", "--json", "--ask-for-approval")


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
    # Login de assinatura: sem ligar contas/API com cobrança automática.
    # O doctor nunca publica tokens ou a resposta completa de auth.
    authentication = {"claude": "unknown", "codex": "unknown"}
    if found["claude"]:
        authenticated = call(["claude", "auth", "status"])
        if authenticated and authenticated.returncode == 0:
            try:
                details = json.loads(authenticated.stdout)
                method = details.get("authMethod") if isinstance(details, dict) else None
                if method in ("claude.ai", "oauth_token"):
                    authentication["claude"] = "subscription"
                elif method in ("api_key", "api_key_helper", "third_party"):
                    authentication["claude"] = "external_billing_blocked"
            except (TypeError, ValueError):
                pass
    if found["codex"]:
        authenticated = call(["codex", "login", "status"])
        if authenticated and authenticated.returncode == 0:
            output = (authenticated.stdout + authenticated.stderr).casefold()
            if "logged in using chatgpt" in output:
                authentication["codex"] = "subscription"
            elif "api key" in output or "api_key" in output:
                authentication["codex"] = "external_billing_blocked"

    image = os.environ.get("NIVON_PYTHON_IMAGE", "python:3.11-slim")
    image_ok = bool(re.fullmatch(r"python:3\.11(?:-slim)?", image))
    local_image = False
    if found["docker"] and image_ok:
        result = call(["docker", "image", "inspect", image])
        local_image = bool(result and result.returncode == 0)
    # O runner usa sinais POSIX para confirmar encerramento de subprocessos.
    # No Windows nativo, taskkill /T /F não fornece confirmação suficiente;
    # usar Linux/WSL2 até existir isolamento validado por Job Objects.
    host_supported = os.name == "posix"
    return {
        "supported_host": host_supported,
        "host_process_family": os.name,
        "required": {k: found[k] for k in REQUIRED},
        "optional": {k: found[k] for k in OPTIONAL},
        "supported_flags": flags,
        "authentication": authentication,
        "docker_image_local": local_image,
        "docker_image_allowed": image_ok,
        "ready_for_pilot": (
            host_supported and all(found[x] for x in REQUIRED) and image_ok and local_image
            and all(all(v.values()) for v in flags.values())
            and all(value == "subscription" for value in authentication.values())
        ),
        "local_model_option": ("ollama_available_manual_configuration"
                                if found.get("ollama") else "ollama_not_installed"),
        "limits": "Verifica tipo aparente do login, não a cota disponível, RAM/VRAM, licença, isolamento efetivo ou cobrança futura.",
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
