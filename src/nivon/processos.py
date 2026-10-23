"""Execução local de CLIs com timeout e encerramento da árvore de processos.

Uma assinatura pode atingir cotas, travar ou tentar manter subprocessos vivos.
Em POSIX, um grupo/sessão isolado permite encerrar todos os descendentes que
permaneçam no grupo. No Windows, taskkill /T /F tenta encerrar a árvore.
Não há chamadas de rede, não fornece permissões ampliadas.
"""
from __future__ import annotations

from dataclasses import dataclass
import os
from pathlib import Path
import signal
import subprocess
import time


@dataclass(frozen=True)
class Resultado:
    exit_code: int | None
    timed_out: bool
    cleanup_confirmed: bool


def _terminate_tree(process):
    """Timeout kills the dedicated process group, not other user processes."""
    if os.name == "posix":
        group = process.pid
        try:
            os.killpg(group, signal.SIGTERM)
        except ProcessLookupError:
            pass
        try:
            process.wait(timeout=2)
        except subprocess.TimeoutExpired:
            pass
        # The CLI parent can exit before its child; still kill the process group.
        try:
            os.killpg(group, signal.SIGKILL)
        except ProcessLookupError:
            pass
        try:
            process.wait(timeout=2)
        except subprocess.TimeoutExpired:
            pass
        try:
            os.killpg(group, 0)
        except ProcessLookupError:
            return True
        except PermissionError:
            return False
        return False

    # Windows: kill descendants first via taskkill, then confirm parent exit.
    try:
        subprocess.run(["taskkill", "/PID", str(process.pid), "/T", "/F"],
                       timeout=8, capture_output=True, check=False)
    except (OSError, subprocess.SubprocessError):
        pass
    if process.poll() is None:
        try:
            process.kill()
        except OSError:
            pass
    try:
        process.wait(timeout=3)
    except subprocess.TimeoutExpired:
        return False
    # Native Windows cannot cheaply guarantee children died without OS queries.
    return False


def executar_cli(argv, *, cwd, logfile, env, timeout_seconds):
    """Bounded subprocess. Leaves full log local; never returns log text."""
    if type(timeout_seconds) not in (int, float) or not 1 <= timeout_seconds <= 3600:
        raise ValueError("Prazo da CLI inválido")
    if not isinstance(argv, (list, tuple)) or not argv or not all(
            isinstance(item, str) and item for item in argv):
        raise ValueError("Argumentos da CLI inválidos")
    cwd = Path(cwd)
    logfile = Path(logfile)
    if not cwd.is_dir():
        raise ValueError("Worktree inexistente")
    if logfile.exists():
        raise FileExistsError("Log já existente; não sobrescrever sessão antiga")
    logfile.parent.mkdir(parents=True, exist_ok=True)

    kwargs = {"cwd": str(cwd), "stdin": subprocess.DEVNULL,
              "stderr": subprocess.STDOUT, "env": env}
    if os.name == "posix":
        kwargs["start_new_session"] = True
    elif os.name == "nt":
        kwargs["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP
    else:
        raise RuntimeError("Sistema operacional não suportado para isolamento de processos")

    # Mode x: no reuse, keep log private.
    fd = os.open(logfile, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as destination:
        try:
            process = subprocess.Popen(argv, stdout=destination, **kwargs)
        except BaseException:
            # Nothing launched: remove the freshly-created empty log.
            logfile.unlink(missing_ok=True)
            raise
        try:
            exit_code = process.wait(timeout=timeout_seconds)
            # Um comando pode terminar normalmente e deixar subprocessos vivos.
            # Também encerra/removê-los após saída 0 para evitar work noturno órfão.
            confirmed = _terminate_tree(process)
            return Resultado(exit_code=exit_code, timed_out=False, cleanup_confirmed=confirmed)
        except subprocess.TimeoutExpired:
            confirmed = _terminate_tree(process)
            return Resultado(exit_code=process.poll(), timed_out=True,
                             cleanup_confirmed=confirmed)
        except BaseException:
            _terminate_tree(process)
            raise
