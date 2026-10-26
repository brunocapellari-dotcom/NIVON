"""NIVON: validar e selecionar tarefas de cloud agents sem invocar modelo ou GitHub API.

O arquivo JSON é uma agenda de issues; seleção não cria PR, não agenda execução
e não ativa infraestrutura. O status real de cada issue deve ser consultado no
GitHub antes de iniciar um agente.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path, PurePosixPath
import re
import sys

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_FILE = ROOT / "docs" / "NIVON_BACKLOG_EXECUCAO.json"
REPO = "brunocapellari-dotcom/NIVON"
AGENTS = {"claude", "codex", "human"}
PRIORITY = {"P0": 0, "P1": 1, "P2": 2}
READINESS = {"ready_code", "review_required", "external_gate"}
MAX_TASKS = 100
PATTERN = re.compile(r"^[a-z0-9][a-z0-9_-]{3,80}$")
ISSUE_URL = re.compile(r"^https://github\.com/brunocapellari-dotcom/NIVON/issues/(\d+)$")


def safe_path(raw, root=ROOT):
    if not isinstance(raw, str) or len(raw) > 200 or "\\" in raw or raw.startswith("/"):
        raise ValueError("Caminho absoluto/inválido")
    parts = PurePosixPath(raw).parts
    if len(parts) < 2 or parts[0] not in {"src", "docs", "tests", ".github", "scripts"}:
        raise ValueError("Arquivo fora do repositório")
    if any(x in {"..", "."} or x.startswith(".env") for x in parts):
        raise ValueError("Travessia de diretório ou secrets")
    candidate = root.joinpath(*parts)
    if candidate.is_symlink() or any(p.is_symlink() for p in candidate.parents if p != root.parent):
        raise ValueError("Symlinks não permitidos")
    if not candidate.is_file():
        raise ValueError("Arquivo do escopo não existe na branch: " + raw)
    return raw


def load(path=DEFAULT_FILE, root=ROOT):
    obj = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(obj, dict) or obj.get("schema_version") != 1 or obj.get("repository") != REPO:
        raise ValueError("Manifesto NIVON desconhecido")
    tasks = obj.get("tasks")
    if not isinstance(tasks, list) or len(tasks) == 0 or len(tasks) > MAX_TASKS:
        raise ValueError("Quantidade de tarefas inválida")
    ids, issues, normalized = set(), set(), []
    for row in tasks:
        if not isinstance(row, dict):
            raise ValueError("Registro de tarefa inválido")
        ident, issue = row.get("id"), row.get("issue")
        if not isinstance(ident, str) or not PATTERN.fullmatch(ident) or ident in ids:
            raise ValueError("ID de tarefa inválido ou repetido")
        if type(issue) is not int or issue < 1 or issue in issues:
            raise ValueError("Issue inválida ou repetida")
        url = row.get("issue_url", "")
        m = ISSUE_URL.fullmatch(url) if isinstance(url, str) else None
        if not m or int(m.group(1)) != issue:
            raise ValueError("URL de issue não corresponde ao ID")
        if row.get("priority") not in PRIORITY or row.get("preferred_agent") not in AGENTS:
            raise ValueError("Prioridade ou agente inválido")
        if row.get("readiness") not in READINESS:
            raise ValueError("Estado inválido")
        files = row.get("files")
        if not isinstance(files, list) or not files or len(files) > 8:
            raise ValueError("Escopo de arquivos inválido")
        files = sorted({safe_path(f, root) for f in files})
        deps = row.get("depends_on", [])
        if not isinstance(deps, list) or not all(isinstance(d, str) for d in deps):
            raise ValueError("Dependências inválidas")
        text = row.get("acceptance", "")
        if not isinstance(text, str) or len(text) < 10 or len(text) > 500:
            raise ValueError("Critério de aceite inválido")
        ids.add(ident)
        issues.add(issue)
        normalized.append({**row, "files": files, "depends_on": deps})
    for row in normalized:
        if row["id"] in row["depends_on"] or any(d not in ids for d in row["depends_on"]):
            raise ValueError("Dependência circular imediata ou inexistente")
    graph = {r["id"]: r["depends_on"] for r in normalized}
    visited, visiting = set(), set()

    def walk(key):
        if key in visiting:
            raise ValueError("Ciclo na fila")
        if key in visited:
            return
        visiting.add(key)
        for dep in graph[key]:
            walk(dep)
        visiting.remove(key)
        visited.add(key)

    for ident in ids:
        walk(ident)
    return normalized


def select(tasks, *, agent="codex", limit=3, completed=()):
    if agent not in {"claude", "codex"} or type(limit) is not int or not 1 <= limit <= 10:
        raise ValueError("Consulta inválida")
    complete = set(completed)
    reserved, ready = set(), []
    for row in sorted(tasks, key=lambda x: (PRIORITY[x["priority"]], x["issue"])):
        if row["preferred_agent"] != agent or row["readiness"] != "ready_code":
            continue
        if any(dependency not in complete for dependency in row["depends_on"]):
            continue
        overlap = reserved.intersection(row["files"])
        if overlap:
            continue
        ready.append({key: row[key] for key in (
            "id", "issue", "issue_url", "priority", "preferred_agent",
            "files", "acceptance")})
        reserved.update(row["files"])
        if len(ready) >= limit:
            break
    return ready


def main(argv=None):
    parser = argparse.ArgumentParser(description="Fila cloud NIVON: somente leitura e sem tokens")
    parser.add_argument("action", choices=("validate", "select", "summary"))
    parser.add_argument("--manifest", type=Path, default=DEFAULT_FILE)
    parser.add_argument("--agent", choices=("claude", "codex"), default="codex")
    parser.add_argument("--limit", type=int, default=3)
    args = parser.parse_args(argv)
    try:
        rows = load(args.manifest)
        if args.action == "validate":
            result = {"valid": True, "tasks": len(rows), "issues": len({r["issue"] for r in rows})}
        elif args.action == "summary":
            result = {"tasks": len(rows), "code_ready": sum(r["readiness"] == "ready_code" for r in rows),
                      "external_gate": sum(r["readiness"] == "external_gate" for r in rows),
                      "review_required": sum(r["readiness"] == "review_required" for r in rows)}
        else:
            result = {"agent": args.agent, "candidates": select(rows, agent=args.agent, limit=args.limit),
                      "note": "Sugestões; verificar status atual da issue/PR antes de iniciar Codex/Claude"}
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print("Backlog inválido: " + str(exc), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
