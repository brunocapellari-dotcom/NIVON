"""Checagem local, somente leitura, de divergência antes de integrar PRs.

Não executa merge, rebase, fetch ou push. Local main pode estar desatualizada;
por isso não substitui a comparação remota no GitHub.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]


def git(*args, root=ROOT):
    proc = subprocess.run(["git", *args], cwd=str(root), capture_output=True,
                          timeout=20, check=False)
    if proc.returncode:
        raise RuntimeError("Git local indisponível ou ref inexistente")
    return proc.stdout


def paths(base, revision, *, root=ROOT):
    output = git("diff", "--name-only", "-z", f"{base}..{revision}", root=root)
    return {entry.decode("utf-8", errors="replace") for entry in output.split(b"\0") if entry}


def inspect(root=ROOT):
    root = Path(root)
    if not (root / ".git").exists():
        raise RuntimeError("Execute no checkout do repositório")
    base = git("merge-base", "main", "HEAD", root=root).decode().strip()
    main = git("rev-parse", "main", root=root).decode().strip()
    head = git("rev-parse", "HEAD", root=root).decode().strip()
    main_files = paths(base, "main", root=root)
    branch_files = paths(base, "HEAD", root=root)
    shared = sorted(main_files & branch_files)
    behind = int(git("rev-list", "--count", f"{base}..main", root=root).strip())
    ahead = int(git("rev-list", "--count", f"{base}..HEAD", root=root).strip())
    return {
        "main_local_sha": main, "branch_sha": head, "merge_base_sha": base,
        "main_commits_since_base": behind,
        "branch_commits_since_base": ahead,
        "same_files_modified": shared[:80],
        "same_files_count": len(shared),
        "needs_reconciliation": behind > 0,
        "risk": "same_files_changed" if shared else "new_main_commits" if behind else "none",
        "remote_freshness": "unknown; no git fetch performed",
        "note": "Ausência de interseção de nomes não garante merge sem conflitos.",
    }


def main(argv=None):
    parser = argparse.ArgumentParser(description="NIVON: divergência local de PR sem merge")
    parser.add_argument("command", choices=["check"])
    parser.parse_args(argv)
    try:
        print(json.dumps(inspect(), ensure_ascii=False, indent=2))
        return 0
    except (OSError, ValueError, RuntimeError, subprocess.SubprocessError) as exc:
        print(f"integração: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
