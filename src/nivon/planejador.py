"""Planejador determinístico e incremental para o NIVON.

Prioriza tarefas reais sem usar tokens de LLM. Fontes: roadmap versionado,
lacunas observáveis de testes e issues GitHub explicitamente habilitadas.
GitHub é entrada não confiável: títulos e corpos nunca são comandos.
"""
from __future__ import annotations

import argparse
import ast
import hashlib
import json
from pathlib import Path, PurePosixPath
import re
import shutil
import sqlite3
import subprocess
import sys

from nivon.cooperacao import connect, default_db, overlap, report, seed

HERE = Path(__file__).resolve().parents[2]
DEFAULT_MANIFEST = HERE / "docs" / "PLANEJADOR_ROADMAP.json"
GITHUB_REPO = "brunocapellari-dotcom/NIVON"
MAX_ISSUES = 60
MAX_TASKS = 50
APPROVED_LABEL = "nivon-auto-ready"
APPROVED_BLOCK = re.compile(r"<!--\s*NIVON-AUTO\s*(\{.{0,5000}?\})\s*-->", re.S)
SENSITIVE = re.compile(r"(^\.|\.env|secret|password|credencia|token|private|(?:^|/)infra/)", re.I)
RISK = re.compile(
    r"(licen[cç]a|direitos? de uso|captcha|bypass|pagar|pagamento|billing|deploy|produ[cç][aã]o|"
    r"chave privada|credencia|secret|terraform|drop table|apagar banco|delete database|"
    r"cloud run|recurso pago)", re.I
)
ID = re.compile(r"^[a-z0-9][a-z0-9_-]{2,70}$")
AGENTS = {"claude", "codex", "any"}
RISK_CATEGORIES = {"low", "restricted", "blocked"}


def safe_path(raw, root=HERE):
    """Only tracked source/test paths, not arbitrary files or symlink escapes."""
    if not isinstance(raw, str) or len(raw) > 180 or "\\" in raw or raw.startswith("/"):
        raise ValueError("Caminho inválido")
    parts = PurePosixPath(raw).parts
    if not parts or any(part in {".", ".."} for part in parts):
        raise ValueError("Travessia de diretório")
    if parts[0] not in {"src", "tests"} or SENSITIVE.search(raw):
        raise ValueError("Caminho não autorizado")
    path = (root / raw)
    if path.is_symlink():
        raise ValueError("Symlink não permitido")
    cursor = path.parent
    while cursor != root and cursor != cursor.parent:
        if cursor.is_symlink():
            raise ValueError("Diretório symlink")
        cursor = cursor.parent
    return raw


def normalized(row, root=HERE):
    if not isinstance(row, dict):
        raise ValueError("Tarefa deve ser objeto")
    task_id = row.get("id", "")
    if not isinstance(task_id, str) or not ID.fullmatch(task_id):
        raise ValueError("ID inválido")
    title = row.get("title", "")
    if not isinstance(title, str) or not 8 <= len(title) <= 160:
        raise ValueError("Título inválido")
    scope = row.get("scope")
    if not isinstance(scope, list) or not 1 <= len(scope) <= 6:
        raise ValueError("Escopo inválido")
    paths = sorted({safe_path(p, root) for p in scope})
    if not any((root / p).is_file() for p in paths):
        raise ValueError("Sem código local referenciado")
    depends = row.get("depends_on", [])
    if not isinstance(depends, list) or any(not isinstance(d, str) or not ID.fullmatch(d) for d in depends):
        raise ValueError("Dependências inválidas")
    if task_id in depends:
        raise ValueError("Autodependência")
    priority = row.get("priority", 50)
    if type(priority) is not int or not 1 <= priority <= 1000:
        raise ValueError("Prioridade inválida")
    agent = row.get("preferred_agent", "any")
    if agent not in AGENTS:
        raise ValueError("Agente inválido")
    risk = row.get("risk", "low")
    if risk not in RISK_CATEGORIES:
        raise ValueError("Risco inválido")
    criteria = row.get("acceptance", "")
    if not isinstance(criteria, str) or len(criteria) > 700:
        raise ValueError("Aceite excessivo/inválido")
    return {"id": task_id, "title": title, "scope": paths, "priority": priority,
            "preferred_agent": agent, "risk": risk, "acceptance": criteria,
            "depends_on": sorted(set(depends)), "source": str(row.get("source", "roadmap"))[:120]}


def source_manifest(path=DEFAULT_MANIFEST, root=HERE):
    if not Path(path).exists():
        return []
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(data, list) or len(data) > 200:
        raise ValueError("Manifesto inválido")
    return [normalized(x, root) for x in data]


def get_issues(repo=GITHUB_REPO, *, limit=MAX_ISSUES):
    """Explicitly read-only gh command; never push labels/comments/PRs."""
    if not shutil.which("gh"):
        return [], "gh ausente"
    if repo != GITHUB_REPO:
        return [], "Repositório não permitido"
    proc = subprocess.run(
        ["gh", "issue", "list", "-R", repo, "--state", "open",
         "--limit", str(min(MAX_ISSUES, limit)),
         "--json", "number,title,body,labels,url"],
        text=True, capture_output=True, timeout=20, check=False,
    )
    if proc.returncode:
        return [], "Consulta GitHub indisponível"
    try:
        data = json.loads(proc.stdout)
    except json.JSONDecodeError:
        return [], "Resposta GitHub inválida"
    return (data[:MAX_ISSUES], None) if isinstance(data, list) else ([], "Resposta inválida")


def tasks_from_issues(issues, root=HERE):
    ready, review = [], []
    for issue in issues[:MAX_ISSUES]:
        if not isinstance(issue, dict):
            continue
        number = issue.get("number")
        if type(number) is not int or number < 1:
            continue
        labels = [x.get("name", "") for x in issue.get("labels", []) if isinstance(x, dict)]
        if APPROVED_LABEL not in labels:
            continue
        text = issue.get("body", "")
        if not isinstance(text, str):
            continue
        match = APPROVED_BLOCK.search(text)
        if not match:
            review.append({"issue": number, "reason": "Sem bloco NIVON-AUTO estruturado"})
            continue
        try:
            spec = json.loads(match.group(1))
            if not isinstance(spec, dict):
                raise ValueError("Especificação inválida")
            spec["id"] = f"issue-{number}"
            spec["source"] = f"github-issue-{number}"
            item = normalized(spec, root)
            if RISK.search(item["title"]) or RISK.search(item["acceptance"]):
                raise ValueError("Texto exige revisão humana")
            # Não transformar conteúdo de uma issue em prompt irrestrito.
            # Aceite deve ser preenchido no manifesto canônico, não na issue.
            if item["risk"] != "low":
                raise ValueError("Risco exige intervenção")
            ready.append(item)
        except (ValueError, TypeError, json.JSONDecodeError) as exc:
            review.append({"issue": number, "reason": type(exc).__name__})
    return ready, review


def coverage_candidates(root=HERE, *, maximum=4):
    """Identify modules without an exact test file, avoiding legacy/private collectors."""
    src = root / "src" / "nivon"
    tests = root / "tests"
    if not src.is_dir() or not tests.is_dir():
        return []
    candidates = []
    for module in sorted(src.glob("*.py")):
        if module.name in {"__init__.py", "planejador.py", "autonomia.py", "cooperacao.py"}:
            continue
        if module.stat().st_size > 300_000 or SENSITIVE.search(module.name):
            continue
        name = module.stem
        if (tests / f"test_{name}.py").exists():
            continue
        try:
            tree = ast.parse(module.read_text(encoding="utf-8"))
        except (UnicodeError, SyntaxError):
            continue
        public = [n.name for n in tree.body if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))
                  and not n.name.startswith("_")]
        if not public:
            continue
        candidates.append(normalized({
            "id": f"coverage-{name}",
            "title": f"Implementar testes de integração offline para {name}",
            "scope": [f"src/nivon/{module.name}", f"tests/test_{name}.py"],
            "priority": 90,
            "preferred_agent": "any",
            "acceptance": "Incluir testes de erro, casos de borda e fixtures sintéticas; sem acesso live nem regressões.",
        }, root))
    return candidates[:maximum]


def dependency_order(tasks):
    ids = {t["id"] for t in tasks}
    if len(ids) != len(tasks):
        raise ValueError("IDs repetidos no planejamento")
    graph = {t["id"]: set(d for d in t["depends_on"] if d in ids) for t in tasks}
    states = {}

    def visit(node):
        state = states.get(node, 0)
        if state == 1:
            raise ValueError("Ciclo de dependência")
        if state == 2:
            return
        states[node] = 1
        for dep in graph[node]:
            visit(dep)
        states[node] = 2

    for task in tasks:
        visit(task["id"])
    return tasks


def refresh(db, *, root=HERE, manifest=None, issues=None, include_coverage=True):
    tasks = source_manifest(manifest or root / "docs" / "PLANEJADOR_ROADMAP.json", root)
    imported, rejected = tasks_from_issues(issues or [], root)
    tasks.extend(imported)
    if include_coverage:
        tasks.extend(coverage_candidates(root))
    unique = {}
    for task in tasks:
        unique.setdefault(task["id"], task)
    tasks = dependency_order(list(unique.values()))
    states = {r["id"]: r["status"] for r in db.execute("SELECT id,status FROM tasks")}
    ready = []
    waiting = []
    for t in sorted(tasks, key=lambda x: (x["priority"], x["id"])):
        if t["id"] in states:
            continue
        if t["risk"] != "low":
            waiting.append({"id": t["id"], "reason": "risco não liberado"})
            continue
        pending_deps = [d for d in t["depends_on"] if states.get(d) != "done"]
        if pending_deps:
            waiting.append({"id": t["id"], "reason": "dependências " + ",".join(pending_deps)})
            continue
        if any(overlap(t["scope"], prev["scope"]) for prev in ready):
            # Conflitos são resolvidos via fila no ciclo posterior, sem perda de tarefas.
            waiting.append({"id": t["id"], "reason": "escopo ocupado neste lote"})
            continue
        ready.append(t)
        if len(ready) >= MAX_TASKS:
            break
    added = seed(db, ready) if ready else 0
    return {"added": added, "eligible": [t["id"] for t in ready],
            "waiting": waiting[:80], "github_rejected": rejected[:30],
            "candidates": len(tasks), "existing": len(states)}


def main(argv=None):
    parser = argparse.ArgumentParser(description="Planejador determinístico NIVON; sem LLM")
    parser.add_argument("--db", type=Path)
    sub = parser.add_subparsers(dest="cmd", required=True)
    for cmd in ("refresh", "preview"):
        opt = sub.add_parser(cmd)
        opt.add_argument("--github", action="store_true", help="Consulta gh read-only, se disponível")
        opt.add_argument("--no-coverage", action="store_true")
    args = parser.parse_args(argv)
    try:
        issues, warning = get_issues() if args.github else ([], None)
        with connect(args.db or default_db()) as db:
            if args.cmd == "preview":
                # seed commits its transaction: preview must use a disposable DB.
                memory = sqlite3.connect(":memory:")
                memory.row_factory = sqlite3.Row
                db.backup(memory)
                try:
                    data = refresh(memory, issues=issues,
                                   include_coverage=not args.no_coverage)
                    data["states"] = report(memory)["counts"]
                finally:
                    memory.close()
            else:
                data = refresh(db, issues=issues, include_coverage=not args.no_coverage)
                data["states"] = report(db)["counts"]
            data["github_warning"] = warning
        print(json.dumps(data, indent=2, ensure_ascii=False))
        return 0
    except (ValueError, OSError, sqlite3.Error, json.JSONDecodeError,
            subprocess.SubprocessError) as exc:
        print(f"Planejador NIVON: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
