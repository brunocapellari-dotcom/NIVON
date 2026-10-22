"""NIVON: execução local cooperativa, limitada e retomável de Claude + Codex.

Nenhuma chamada à nuvem acontece até o operador invocar 'start' ou 'run'.
O orquestrador não instala dependências, abre PR, publica dados ou faz deploy.
"""
from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import threading
import time

from nivon.cooperacao import change, claim, connect, default_db, report
from nivon.token_guard import summarize

ROOT = Path(__file__).resolve().parents[2]
HOME = ROOT / ".nivon-local"
QUOTA = re.compile(r"(rate.limit|usage.limit|quota.exceed|limit.reach|too.many.requests|resets.in)", re.I)
IDENT = re.compile(r"^[a-zA-Z0-9_-]{1,70}$")


def command(args, cwd=ROOT, *, timeout=30, env=None):
    return subprocess.run(args, cwd=str(cwd), capture_output=True, text=True,
                          timeout=timeout, check=False, env=env)


def preflight():
    if not (ROOT / ".git").exists():
        raise RuntimeError("Execute no checkout Git do NIVON")
    for tool in ("git", "claude", "codex"):
        if not shutil.which(tool):
            raise RuntimeError(f"CLI não encontrada: {tool}; sem execução/cobrança iniciada")
    result = command(["git", "status", "--porcelain", "--untracked-files=no"])
    if result.returncode or result.stdout.strip():
        raise RuntimeError("Checkout principal precisa estar limpo antes da execução")
    HOME.mkdir(exist_ok=True)
    (HOME / "worktrees").mkdir(exist_ok=True)
    (HOME / "logs").mkdir(exist_ok=True)


def prompt(task):
    scope = json.loads(task["scope"])
    return (
        "NIVON: você é implementador, trabalhando em PARALELO com outro agente. "
        "Tarefa: " + task["title"] + ". ID: " + task["id"] + ".\n"
        "Arquivos permitidos: " + ", ".join(scope) + ".\n"
        "Leia AGENTS.md e apenas os arquivos necessários. "
        "Faça alterações pequenas e úteis e inclua testes sintéticos. "
        "Não altere nada fora do escopo; não instale dependências; "
        "não execute redes, deploy, scraping, serviços cloud, commits ou merges. "
        "Não tente obter credenciais. Testes e commit são feitos pelo orquestrador. "
        "Use busca localizada, não leia logs/repositório inteiros. "
        "No final, responda resumidamente o que alterou."
    )


def cli(agent, task):
    instruction = prompt(task)
    if agent == "claude":
        return ["claude", "-p", "--restricted", "--permission-mode", "acceptEdits",
                "--permission-prompts", "none", "--tools", "Read,Edit,Write,Grep,Glob",
                "--disallowedTools", "mcp__*", "--max-turns", "8",
                "--output-format", "json", instruction]
    if agent == "codex":
        return ["codex", "exec", "--ephemeral", "--json", "--sandbox", "workspace-write",
                "--config", "sandbox_workspace_write.network_access=false",
                "--ask-for-approval", "never", instruction]
    raise ValueError("Agente inválido")


def usage_from_log(logfile):
    """Best-effort CLI-reported tokens; unknown means None, never invent zero."""
    try:
        raw = logfile.read_text(encoding="utf-8", errors="replace")
        events = [json.loads(raw)] if raw.lstrip().startswith("{") and "\n{" not in raw else [
            json.loads(line) for line in raw.splitlines() if line.lstrip().startswith("{")
        ]
        for obj in reversed(events):
            usage = obj.get("usage") or obj.get("total_token_usage")
            if not isinstance(usage, dict):
                continue
            ins, outs = usage.get("input_tokens"), usage.get("output_tokens")
            if isinstance(ins, int) and isinstance(outs, int) and ins >= 0 and outs >= 0:
                return ins, outs
    except (OSError, ValueError, TypeError, AttributeError):
        pass
    return None, None


def within_scope(worktree, allowed):
    changed = command(["git", "status", "--porcelain", "--untracked-files=all"], worktree)
    if changed.returncode:
        raise RuntimeError("git status falhou")
    paths = []
    for line in changed.stdout.splitlines():
        entry = line[3:]
        if " -> " in entry or not entry or entry[0] == '"':
            raise RuntimeError("Mudança renomeada/ambígua exige revisão humana")
        path = Path(entry)
        if path.is_absolute() or ".." in path.parts:
            raise RuntimeError("Caminho alterado inseguro")
        paths.append(path.as_posix())
    for name in paths:
        if not any(name == s or name.startswith(s + "/") for s in allowed):
            raise RuntimeError(f"Alteração fora do escopo: {name}")
        p = worktree / name
        if p.is_symlink():
            raise RuntimeError("Symlink alterado exige revisão")
    return paths


def do_task(agent, task, *, timeout_minutes=15):
    if not IDENT.fullmatch(task["id"]) or task["attempts"] > 2:
        raise RuntimeError("ID inseguro ou limite de tentativas")
    name = f"{task['id']}-{agent}-{task['attempts']}"
    worktree = HOME / "worktrees" / name
    branch = "autonomo/" + name
    if worktree.exists():
        raise RuntimeError("Worktree já existe; verifique antes de retomar")
    make = command(["git", "worktree", "add", "-b", branch, str(worktree), "HEAD"], timeout=60)
    if make.returncode:
        raise RuntimeError("Falha criando worktree: " + make.stderr[:400])
    logfile = HOME / "logs" / (name + ".log")
    logfile.touch(mode=0o600, exist_ok=False)
    runtime_env = os.environ.copy()
    for key in tuple(runtime_env):
        if key.startswith(("AWS_", "GOOGLE_", "GCP_", "AZURE_", "VERCEL_", "NEON_", "SUPABASE_")) or key in (
            "ANTHROPIC_API_KEY", "OPENAI_API_KEY", "CODEX_API_KEY",
            "ANTHROPIC_AUTH_TOKEN", "CLAUDE_CODE_OAUTH_TOKEN",
            "CLAUDECODE", "CLAUDE_CODE_ENTRYPOINT"
        ):
            runtime_env.pop(key, None)
    try:
        with logfile.open("w", encoding="utf-8") as log:
            process = subprocess.run(cli(agent, task), cwd=worktree, stdout=log,
                                     stderr=subprocess.STDOUT, env=runtime_env,
                                     timeout=timeout_minutes * 60, check=False)
        raw = logfile.read_text(encoding="utf-8", errors="replace")
        if process.returncode:
            if QUOTA.search(raw) and task["attempts"] == 1:
                return "quota", f"{branch}; {summarize(raw, 1200)}"
            return "blocked", f"{branch}; CLI código {process.returncode}; {summarize(raw, 1200)}"
        modified = within_scope(worktree, json.loads(task["scope"]))
        if not modified:
            return "blocked", f"{branch}; nenhuma alteração produzida"
        env = os.environ.copy()
        env["PYTHONPATH"] = str(worktree / "src")
        checks = [
            [sys.executable, "-m", "compileall", "-q", "src", "tests"],
            [sys.executable, "-m", "unittest", "discover", "-s", "tests", "-q"]
        ]
        for check in checks:
            tested = command(check, worktree, timeout=180, env=env)
            if tested.returncode:
                return "blocked", f"{branch}; testes falharam: {summarize(tested.stdout + tested.stderr, 1500)}"
        scope = json.loads(task["scope"])
        staged = command(["git", "add", "--", *scope], worktree)
        if staged.returncode:
            return "blocked", f"{branch}; git add falhou"
        committed = command(["git", "commit", "-m", f"feat(nivon): {task['id']} ({agent})"], worktree)
        if committed.returncode:
            return "blocked", f"{branch}; git commit falhou: {summarize(committed.stderr, 500)}"
        sha = command(["git", "rev-parse", "HEAD"], worktree).stdout.strip()
        return "done", f"{branch}; commit {sha}; {len(modified)} arquivos; compileall/unittest OK"
    except subprocess.TimeoutExpired:
        return "blocked", f"{branch}; timeout de {timeout_minutes} min; revisar worktree"


def run(*, max_tasks=8, minutes=120, per_task=15):
    preflight()
    (HOME / "STOP").unlink(missing_ok=True)
    dbpath = default_db()
    deadline = time.monotonic() + minutes * 60
    guard = threading.Lock()
    count = {"value": 0}
    events = []

    def worker(agent):
        while not (HOME / "STOP").exists() and time.monotonic() < deadline:
            with guard:
                if count["value"] >= max_tasks:
                    return
                with connect(dbpath) as db:
                    task = claim(db, agent, minutes=max(per_task + 3, 30))
                if task is None:
                    return
                count["value"] += 1
            try:
                outcome, note = do_task(agent, task, timeout_minutes=per_task)
            except Exception as exc:
                outcome, note = "blocked", f"Erro no executor: {type(exc).__name__}; ver logs locais"
            usage_path = HOME / "logs" / f"{task['id']}-{agent}-{task['attempts']}.log"
            usage_in, usage_out = usage_from_log(usage_path)
            with connect(dbpath) as db:
                if outcome == "quota":
                    next_agent = "codex" if agent == "claude" else "claude"
                    change(db, task["id"], agent, "handoff", note[:2500],
                           tokens_in=usage_in, tokens_out=usage_out, next_agent=next_agent)
                else:
                    change(db, task["id"], agent, outcome, note[:2500],
                           tokens_in=usage_in, tokens_out=usage_out)
            with guard:
                events.append({"task": task["id"], "agent": agent, "status": outcome,
                               "tokens_input": usage_in, "tokens_output": usage_out,
                               "note": note[:300]})
    with ThreadPoolExecutor(max_workers=2, thread_name_prefix="nivon") as pool:
        futures = [pool.submit(worker, agent) for agent in ("claude", "codex")]
        for future in futures:
            future.result()
    with connect(dbpath) as db:
        result = report(db)
    payload = {"executions": events, "counts": result["counts"],
               "stale_needs_review": result["stale_needs_review"]}
    (HOME / "last-run.json").write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    return payload


def main(argv=None):
    parser = argparse.ArgumentParser(description="NIVON desenvolvimento cooperativo: offline no preflight")
    sub = parser.add_subparsers(dest="action", required=True)
    for name in ("start", "run"):
        p = sub.add_parser(name)
        p.add_argument("--max-tasks", type=int, default=8)
        p.add_argument("--minutes", type=int, default=120)
        p.add_argument("--per-task", type=int, default=15)
    sub.add_parser("status")
    sub.add_parser("stop")
    args = parser.parse_args(argv)
    if args.action == "status":
        with connect(default_db()) as db:
            data = report(db)
        print(json.dumps({"counts": data["counts"], "stale": data["stale_needs_review"]},
                         ensure_ascii=False))
        return 0
    if args.action == "stop":
        HOME.mkdir(exist_ok=True)
        (HOME / "STOP").write_text("Parar ao fim da tarefa atual\n", encoding="utf-8")
        print("Solicitada parada cooperativa ao fim das tarefas ativas.")
        return 0
    if not 1 <= args.max_tasks <= 30 or not 1 <= args.minutes <= 480 or not 2 <= args.per_task <= 60:
        parser.error("Limites inválidos")
    try:
        preflight()
        if args.action == "start":
            HOME.mkdir(exist_ok=True)
            destination = HOME / "supervisor.log"
            with destination.open("a", encoding="utf-8") as log:
                argv = [sys.executable, "-m", "nivon.autonomia", "run",
                        "--max-tasks", str(args.max_tasks), "--minutes", str(args.minutes),
                        "--per-task", str(args.per_task)]
                supervisor_env = os.environ.copy()
                supervisor_env.pop("CLAUDECODE", None)
                supervisor_env.pop("CLAUDE_CODE_ENTRYPOINT", None)
                supervisor_env["PYTHONPATH"] = str(ROOT / "src")
                subprocess.Popen(argv, cwd=str(ROOT), stdin=subprocess.DEVNULL,
                                 stdout=log, stderr=subprocess.STDOUT,
                                 start_new_session=True, env=supervisor_env)
            print(f"Orquestrador iniciado no host. Log local: {destination}")
            return 0
        print(json.dumps(run(max_tasks=args.max_tasks, minutes=args.minutes,
                             per_task=args.per_task), ensure_ascii=False))
        return 0
    except (ValueError, RuntimeError, OSError, subprocess.SubprocessError) as exc:
        print(f"NIVON autonômo: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
