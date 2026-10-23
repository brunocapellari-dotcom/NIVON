"""NIVON: execução local cooperativa, limitada e retomável de Claude + Codex.

Nenhuma chamada à nuvem acontece até o operador invocar 'start' ou 'run'.
O orquestrador não instala dependências, abre PR, publica dados ou faz deploy.
"""
from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
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
from nivon.planejador import get_issues, refresh as refresh_plan
from nivon.contexto_codigo import capsule
from nivon.token_guard import summarize
from nivon.metricas import parse_file
from nivon.ferramentas import doctor as check_tools
from nivon.processos import executar_cli
from nivon.janela_noturna import may_begin, status as night_status

ROOT = Path(__file__).resolve().parents[2]
HOME = ROOT / ".nivon-local"
INTEGRATION_LOCK = threading.Lock()
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
    # Confirma flags da CLI e login de assinatura sem chamar nenhum modelo.
    readiness = check_tools()
    if not readiness["ready_for_pilot"]:
        raise RuntimeError("Doctor rejeitou CLI, autenticação, flags ou sandbox Docker; execute bash scripts/nivon-autonomo.sh doctor")
    result = command(["git", "status", "--porcelain", "--untracked-files=no"])
    if result.returncode or result.stdout.strip():
        raise RuntimeError("Checkout principal precisa estar limpo antes da execução")
    # Testes executam código produzido por LLM: exigir Docker local offline.
    if not shutil.which("docker"):
        raise RuntimeError("Docker requerido para testes isolados sem rede")
    image = os.environ.get("NIVON_PYTHON_IMAGE", "python:3.11-slim")
    if not re.fullmatch(r"python:3\.11(?:-slim)?", image):
        raise RuntimeError("Imagem Python fora da lista aprovada")
    available = command(["docker", "image", "inspect", image], timeout=10)
    if available.returncode:
        raise RuntimeError("Imagem Docker local não encontrada; instalação/pull automático bloqueado")
    HOME.mkdir(exist_ok=True)
    (HOME / "worktrees").mkdir(exist_ok=True)
    (HOME / "logs").mkdir(exist_ok=True)


def prepare_integration():
    """Cria uma única branch/worktree de integração local, nunca a main."""
    location = HOME / "integration"
    if location.exists():
        head = command(["git", "branch", "--show-current"], location)
        if head.returncode or head.stdout.strip() != "autonomo/integracao":
            raise RuntimeError("Worktree de integração inválida")
        return location
    known = command(["git", "show-ref", "--verify", "refs/heads/autonomo/integracao"])
    args = (["git", "worktree", "add", str(location), "autonomo/integracao"]
            if known.returncode == 0
            else ["git", "worktree", "add", "-b", "autonomo/integracao", str(location), "HEAD"])
    created = command(args, timeout=60)
    if created.returncode:
        raise RuntimeError("Não foi possível preparar branch de integração local")
    return location


def prompt(task):
    scope = json.loads(task["scope"])
    context = capsule(task, root=(HOME / "integration" if (HOME / "integration").is_dir() else ROOT), limit=450)
    hint = ("Mapa de símbolos (somente metadados): " + context + "\n") if context else ""
    return (
        "NIVON: você é implementador, trabalhando em PARALELO com outro agente. "
        "Tarefa: " + task["title"] + ". ID: " + task["id"] + ".\n"
        "Arquivos permitidos: " + ", ".join(scope) + ".\n"
        "Critério de aceite: " + str(task.get("acceptance") or "Testes de regressão offline e sem efeitos externos")[:700] + ".\n"
        + hint +
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
        return ["claude", "-p", "--restricted", "--safe-mode", "--no-session-persistence",
                "--permission-mode", "acceptEdits",
                "--permission-prompts", "none", "--tools", "Read,Edit,Write,Grep,Glob",
                "--disallowedTools", "mcp__*", "--max-turns", "8",
                "--output-format", "json", instruction]
    if agent == "codex":
        return ["codex", "exec", "--ephemeral", "--json", "--sandbox", "workspace-write",
                "--config", "sandbox_workspace_write.network_access=false",
                "--ask-for-approval", "never", instruction]
    raise ValueError("Agente inválido")


def usage_from_log(logfile):
    """Backward-compatible helper; new code also tracks cached tokens per CLI."""
    metrics = parse_file(logfile, "claude") or parse_file(logfile, "codex")
    if metrics is None:
        return None, None
    return metrics["input"], metrics["output"]


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


def integrate_local(commit_sha, image):
    """Promove commit aprovado somente à branch interna, com teste pós-integração."""
    with INTEGRATION_LOCK:
        integration = prepare_integration()
        before = command(["git", "rev-parse", "HEAD"], integration)
        if before.returncode:
            return False, "HEAD da integração indisponível"
        clean = command(["git", "status", "--porcelain"], integration)
        if clean.returncode or clean.stdout.strip():
            return False, "Worktree de integração alterada externamente"
        cherry = command(["git", "-c", "core.hooksPath=/dev/null",
                          "-c", "commit.gpgsign=false", "cherry-pick", commit_sha],
                         integration, timeout=60)
        if cherry.returncode:
            command(["git", "cherry-pick", "--abort"], integration, timeout=20)
            return False, "Conflito de integração; alterações preservadas na branch da tarefa"
        sandbox = ["docker", "run", "--rm", "--pull", "never", "--network", "none",
                   "--cap-drop", "ALL", "--security-opt", "no-new-privileges",
                   "--pids-limit", "128", "--memory", "512m", "--cpus", "1",
                   "--read-only", "--tmpfs", "/tmp:rw,noexec,nosuid,size=64m",
                   "--mount", f"type=bind,src={integration},dst=/workspace,readonly",
                   "--workdir", "/workspace", "--env", "PYTHONPATH=/workspace/src",
                   "--env", "PYTHONDONTWRITEBYTECODE=1"]
        if hasattr(os, "getuid") and hasattr(os, "getgid"):
            sandbox += ["--user", f"{os.getuid()}:{os.getgid()}"]
        tests = command([*sandbox, image, "python", "-m", "unittest",
                         "discover", "-s", "tests", "-q"], integration, timeout=180)
        if tests.returncode:
            # Safe: restores only our own dedicated integration worktree.
            command(["git", "-c", "core.hooksPath=/dev/null",
                     "reset", "--hard", before.stdout.strip()], integration, timeout=30)
            return False, "Regressão pós-cherry-pick; branch de implementação preservada"
        sha = command(["git", "rev-parse", "HEAD"], integration).stdout.strip()
        return True, f"SHA de integração {sha}; testes offline OK"


def do_task(agent, task, *, timeout_minutes=15):
    if not IDENT.fullmatch(task["id"]) or task["attempts"] > 2:
        raise RuntimeError("ID inseguro ou limite de tentativas")
    name = f"{task['id']}-{agent}-{task['attempts']}"
    worktree = HOME / "worktrees" / name
    branch = "autonomo/" + name
    if worktree.exists():
        raise RuntimeError("Worktree já existe; verifique antes de retomar")
    make = command(["git", "worktree", "add", "-b", branch, str(worktree),
                    "autonomo/integracao"], timeout=60)
    if make.returncode:
        raise RuntimeError("Falha criando worktree: " + make.stderr[:400])
    logfile = HOME / "logs" / (name + ".log")
    runtime_env = os.environ.copy()
    for key in tuple(runtime_env):
        if key.startswith(("AWS_", "GOOGLE_", "GCP_", "AZURE_", "VERCEL_", "NEON_", "SUPABASE_")) or key in (
            "ANTHROPIC_API_KEY", "OPENAI_API_KEY", "CODEX_API_KEY",
            "ANTHROPIC_AUTH_TOKEN", "CLAUDE_CODE_OAUTH_TOKEN",
            "CLAUDECODE", "CLAUDE_CODE_ENTRYPOINT",
            "CODEX_ACCESS_TOKEN", "OPENAI_FEDERATION_RULE_ID",
            "OPENAI_IDENTITY_TOKEN_FILE", "OPENAI_WORKLOAD_IDENTITY_CONTEXT",
            "CLAUDE_CODE_USE_BEDROCK", "CLAUDE_CODE_USE_VERTEX",
            "CLAUDE_CODE_USE_FOUNDRY"
        ):
            runtime_env.pop(key, None)
    try:
        process = executar_cli(cli(agent, task), cwd=worktree, logfile=logfile,
                               env=runtime_env, timeout_seconds=timeout_minutes * 60)
        if process.timed_out:
            if not process.cleanup_confirmed:
                # Falha em provar a parada dos descendentes: não iniciar novas tarefas.
                (HOME / "STOP").write_text(
                    "Timeout sem encerramento confirmado do grupo de processos; revisão humana\n",
                    encoding="utf-8")
                return "blocked", f"{branch}; timeout, parada dos descendentes NÃO comprovada"
            return "blocked", f"{branch}; timeout de {timeout_minutes} min; processos encerrados"
        if process.exit_code:
            raw = logfile.read_text(encoding="utf-8", errors="replace")
            if QUOTA.search(raw) and task["attempts"] == 1:
                return "quota", f"{branch}; {summarize(raw, 1200)}"
            return "blocked", f"{branch}; CLI código {process.exit_code}; {summarize(raw, 1200)}"
        modified = within_scope(worktree, json.loads(task["scope"]))
        if not modified:
            return "blocked", f"{branch}; nenhuma alteração produzida"
        image = os.environ.get("NIVON_PYTHON_IMAGE", "python:3.11-slim")
        sandbox = ["docker", "run", "--rm", "--pull", "never", "--network", "none",
                   "--cap-drop", "ALL", "--security-opt", "no-new-privileges",
                   "--pids-limit", "128", "--memory", "512m", "--cpus", "1",
                   "--read-only", "--tmpfs", "/tmp:rw,noexec,nosuid,size=64m",
                   "--mount", f"type=bind,src={worktree},dst=/workspace,readonly",
                   "--workdir", "/workspace", "--env", "PYTHONPATH=/workspace/src",
                   "--env", "PYTHONDONTWRITEBYTECODE=1"]
        if hasattr(os, "getuid") and hasattr(os, "getgid"):
            sandbox += ["--user", f"{os.getuid()}:{os.getgid()}"]
        checks = [
            ["python", "-m", "nivon.qualidade", "--json"],
            ["python", "-m", "unittest", "discover", "-s", "tests", "-q"]
        ]
        for check in checks:
            tested = command([*sandbox, image, *check], worktree, timeout=180)
            if tested.returncode:
                return "blocked", f"{branch}; sandbox/testes falharam: {summarize(tested.stdout + tested.stderr, 1500)}"
        # Ruff é opcional; pode rodar no host apenas como analisador de texto, sem importar o projeto.
        py_changed = [name for name in modified if name.endswith(".py")]
        if py_changed and shutil.which("ruff"):
            linted = command(["ruff", "check", "--output-format", "concise", "--", *py_changed],
                             worktree, timeout=90)
            if linted.returncode:
                return "blocked", f"{branch}; Ruff: {summarize(linted.stdout + linted.stderr, 1500)}"
        scope = json.loads(task["scope"])
        staged = command(["git", "add", "--", *scope], worktree)
        if staged.returncode:
            return "blocked", f"{branch}; git add falhou"
        committed = command(["git", "-c", "core.hooksPath=/dev/null",
                             "-c", "commit.gpgsign=false", "commit",
                             "-m", f"feat(nivon): {task['id']} ({agent})"], worktree)
        if committed.returncode:
            return "blocked", f"{branch}; git commit falhou: {summarize(committed.stderr, 500)}"
        sha = command(["git", "rev-parse", "HEAD"], worktree).stdout.strip()
        merged, integration_note = integrate_local(sha, image)
        if not merged:
            return "blocked", f"{branch}; commit {sha}; integração pendente: {integration_note}"
        return "done", f"{branch}; commit {sha}; integrado localmente; {integration_note}"
    except subprocess.TimeoutExpired:
        return "blocked", f"{branch}; timeout de {timeout_minutes} min; revisar worktree"


@contextmanager
def supervisor_lock():
    """Evita supervisores simultâneos; lock órfão exige inspeção, não é roubado."""
    HOME.mkdir(parents=True, exist_ok=True)
    path = HOME / "supervisor.pid"
    try:
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except FileExistsError as exc:
        raise RuntimeError("Supervisor já ativo ou lock órfão; inspeção local necessária") from exc
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(str(os.getpid()) + "\n")
        yield
    finally:
        path.unlink(missing_ok=True)


def run(*, max_tasks=8, minutes=120, per_task=15):
    if not may_begin(per_task_minutes=per_task):
        raise RuntimeError("Desenvolvimento autônomo permitido somente 20:00–06:00 em America/Cuiaba; reserva de tempo para testes")
    preflight()
    with supervisor_lock():
        return _run_locked(max_tasks=max_tasks, minutes=minutes, per_task=per_task)


def _run_locked(*, max_tasks=8, minutes=120, per_task=15):
    (HOME / "STOP").unlink(missing_ok=True)
    dbpath = default_db()
    # Ler GitHub no host (não dentro dos agentes); falhas de rede não bloqueiam tarefas locais.
    github_issues = []
    if os.environ.get("NIVON_GITHUB_READONLY", "1") == "1":
        try:
            github_issues, _ = get_issues()
        except (OSError, subprocess.SubprocessError):
            pass
    prepare_integration()
    with connect(dbpath) as db:
        refresh_plan(db, root=HOME / "integration", issues=github_issues)
    deadline = time.monotonic() + minutes * 60
    guard = threading.Lock()
    count = {"value": 0}
    events = []

    def worker(agent):
        idle_without_other = 0
        while (not (HOME / "STOP").exists() and time.monotonic() < deadline
               and may_begin(per_task_minutes=per_task)):
            with guard:
                if not may_begin(per_task_minutes=per_task):
                    return
                if count["value"] >= max_tasks:
                    return
                with connect(dbpath) as db:
                    task = claim(db, agent, minutes=max(per_task + 3, 30))
                    if task is None:
                        # Um agente pode alcançar sua cota e transferir uma tarefa
                        # somente depois de concluir a tentativa atual. Não encerrar
                        # o colega prematuramente enquanto houver trabalho em curso.
                        other_running = db.execute(
                            "SELECT COUNT(*) FROM tasks WHERE status='running' AND owner<>?",
                            (agent,)).fetchone()[0] > 0
                    else:
                        other_running = False
                if task is None:
                    idle_without_other = 0 if other_running else idle_without_other + 1
                    if idle_without_other >= 3:
                        return
                else:
                    idle_without_other = 0
                    count["value"] += 1
            if task is None:
                # Aguarda sem fazer chamadas a Claude/Codex. Prazo, STOP e
                # janela noturna são reavaliados no início da próxima passagem.
                time.sleep(0.25)
                continue
            try:
                outcome, note = do_task(agent, task, timeout_minutes=per_task)
            except Exception as exc:
                outcome, note = "blocked", f"Erro no executor: {type(exc).__name__}; ver logs locais"
            usage_path = HOME / "logs" / f"{task['id']}-{agent}-{task['attempts']}.log"
            usage = parse_file(usage_path, agent)
            usage_in = usage["input"] if usage else None
            usage_out = usage["output"] if usage else None
            usage_cached = usage["cached_input"] if usage else None
            with connect(dbpath) as db:
                if outcome == "quota":
                    next_agent = "codex" if agent == "claude" else "claude"
                    change(db, task["id"], agent, "handoff", note[:2500],
                           tokens_in=usage_in, tokens_out=usage_out,
                           tokens_cached=usage_cached, next_agent=next_agent)
                else:
                    change(db, task["id"], agent, outcome, note[:2500],
                           tokens_in=usage_in, tokens_out=usage_out,
                           tokens_cached=usage_cached)
                # Replanejar a partir das dependências que acabaram de ser entregues.
                # Não invoca outro LLM e não reativa tarefas bloqueadas.
                if outcome == "done":
                    refresh_plan(db, root=HOME / "integration", issues=github_issues)
            with guard:
                events.append({"task": task["id"], "agent": agent, "status": outcome,
                               "tokens_input": usage_in, "tokens_output": usage_out,
                               "tokens_cached_input": usage_cached,
                               "usage_source": usage["source"] if usage else None,
                               "note": note[:300]})
    with ThreadPoolExecutor(max_workers=2, thread_name_prefix="nivon") as pool:
        futures = [pool.submit(worker, agent) for agent in ("claude", "codex")]
        for future in futures:
            future.result()
    with connect(dbpath) as db:
        result = report(db)
    payload = {"executions": events, "counts": result["counts"],
               "token_metrics": result["tokens_reported"],
               "agents": result["agents"],
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
        print(json.dumps({"counts": data["counts"], "stale": data["stale_needs_review"],
                          "janela_noturna": night_status()}, ensure_ascii=False))
        return 0
    if args.action == "stop":
        HOME.mkdir(exist_ok=True)
        (HOME / "STOP").write_text("Parar ao fim da tarefa atual\n", encoding="utf-8")
        print("Solicitada parada cooperativa ao fim das tarefas ativas.")
        return 0
    if not 1 <= args.max_tasks <= 30 or not 1 <= args.minutes <= 480 or not 2 <= args.per_task <= 60:
        parser.error("Limites inválidos")
    try:
        if not may_begin(per_task_minutes=args.per_task):
            raise RuntimeError("Execução autônoma somente no período noturno de Mato Grosso (20:00–06:00), com margem de conclusão")
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
