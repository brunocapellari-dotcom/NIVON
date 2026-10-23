"""Qualidade estrutural diurna sem LLM, rede nem execução do código inspecionado.

Oferece análise AST integral e Ruff opcional. Não corrige automaticamente e
não usa ferramentas de segurança com possíveis serviços externos.
"""
from __future__ import annotations

import argparse
import ast
import json
from pathlib import Path
import shutil
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]
MAX_FILES = 3000
MAX_REPORT = 20


def python_files(root=ROOT):
    result = []
    for part in ("src", "tests"):
        directory = root / part
        if not directory.is_dir():
            continue
        for path in directory.rglob("*.py"):
            if path.is_symlink() or any(p in {"__pycache__", ".venv", "venv"} for p in path.parts):
                continue
            result.append(path)
            if len(result) >= MAX_FILES:
                return sorted(result)
    return sorted(result)


def syntax_scan(root=ROOT):
    paths = python_files(root)
    issues = []
    for path in paths:
        try:
            content = path.read_bytes()
            if len(content) > 1_000_000:
                raise ValueError("arquivo >1MB exige inspeção")
            ast.parse(content.decode("utf-8"), filename=str(path))
        except (SyntaxError, UnicodeError, ValueError, OSError) as exc:
            issues.append({
                "file": path.relative_to(root).as_posix(),
                "error": type(exc).__name__,
                "line": getattr(exc, "lineno", None)
            })
    return {"files_checked": len(paths), "errors": len(issues), "samples": issues[:MAX_REPORT],
            "truncated": len(paths) >= MAX_FILES}


def ruff_scan(root=ROOT):
    if not shutil.which("ruff"):
        return {"status": "not_installed", "diagnostics": None}
    try:
        proc = subprocess.run(
            ["ruff", "check", "--no-cache", "--select", "E9,F821,F822,F823",
             "--output-format", "json", "src", "tests"],
            cwd=str(root), capture_output=True, text=True, check=False, timeout=45
        )
    except (OSError, subprocess.SubprocessError):
        return {"status": "unavailable", "diagnostics": None}
    if proc.returncode not in (0, 1):
        return {"status": "error", "diagnostics": None}
    try:
        records = json.loads(proc.stdout)
    except (TypeError, json.JSONDecodeError):
        return {"status": "invalid_json", "diagnostics": None}
    if not isinstance(records, list):
        return {"status": "invalid_json", "diagnostics": None}
    samples = []
    for r in records[:MAX_REPORT]:
        if not isinstance(r, dict):
            continue
        file = r.get("filename", "")
        try:
            relative = str(Path(file).resolve().relative_to(root.resolve()))
        except (ValueError, OSError):
            relative = "outside"
        samples.append({"file": relative, "code": r.get("code"),
                        "line": (r.get("location") or {}).get("row")})
    return {"status": "ok" if proc.returncode == 0 else "findings",
            "diagnostics": len(records), "samples": samples}


def report(root=ROOT):
    syntax = syntax_scan(root)
    ruff = ruff_scan(root)
    return {"structural": syntax, "ruff": ruff,
            "passed": syntax["errors"] == 0 and not syntax["truncated"]
            and ruff.get("status") in {"ok", "not_installed"}}


def main(argv=None):
    parser = argparse.ArgumentParser(description="NIVON: qualidade offline sem tokens")
    parser.add_argument("--json", action="store_true", help="Resumo JSON conciso")
    args = parser.parse_args(argv)
    result = report()
    print(json.dumps(result, ensure_ascii=False, indent=2 if args.json else None))
    return 0 if result["passed"] else 2


if __name__ == "__main__":
    sys.exit(main())
