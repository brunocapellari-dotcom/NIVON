"""Executor de inspeção em processo filho com limites determinísticos Linux/POSIX.

Reduz impacto de XLSX malformado com tempo, CPU, memória, descritores e
tamanho máximo de arquivos escritos. NÃO é sandbox contra exfiltração nem
bloqueio de rede; para RAW adversarial, usar também contêiner sem rede e
filesystem restrito. Sem publicação, downloads ou reprocessamento automático.
"""
from __future__ import annotations

import argparse
import os
from pathlib import Path
import signal
import subprocess
import sys


class ErroIsolamentoConab(ValueError):
    pass


def _limites():
    try:
        import resource
        limits = (
            (resource.RLIMIT_CPU, 45, 45),
            (resource.RLIMIT_AS, 1536 * 1024 * 1024, 1536 * 1024 * 1024),
            (resource.RLIMIT_FSIZE, 32 * 1024 * 1024, 32 * 1024 * 1024),
            (resource.RLIMIT_NOFILE, 64, 64),
            (resource.RLIMIT_CORE, 0, 0),
        )
        for kind, soft, hard in limits:
            resource.setrlimit(kind, (soft, hard))
    except (ImportError, OSError, ValueError) as exc:
        # Não avançar fingindo sandbox quando um limite falha.
        raise OSError("limites do worker não aplicáveis") from exc


def executar_worker_conab(
    *, manifesto: str, base_dir: str, saida: str,
    sqlite: str | None = None, timeout_s: int = 75,
) -> dict:
    """Aciona CLI fixo em subprocesso, sem permitir shell ou comando arbitrário."""
    if sys.platform != "linux" or os.name != "posix":
        raise ErroIsolamentoConab("limites de worker exigem Linux")
    if type(timeout_s) is not int or not 5 <= timeout_s <= 90:
        raise ErroIsolamentoConab("timeout deve ficar entre 5 e 90 segundos")
    for key, val in (("manifesto", manifesto), ("base_dir", base_dir),
                     ("saida", saida)):
        if not isinstance(val, str) or not val or "\x00" in val or len(val) > 1024:
            raise ErroIsolamentoConab("caminho inválido: " + key)
    if sqlite is not None and (not isinstance(sqlite, str) or
                                not sqlite or "\x00" in sqlite or len(sqlite) > 1024):
        raise ErroIsolamentoConab("caminho SQLite inválido")
    args = [
        sys.executable, "-m", "nivon.conab_lote_offline",
        "--manifest", manifesto, "--base-dir", base_dir, "--out", saida,
    ]
    if sqlite is not None:
        args.extend(("--sqlite", sqlite))
    # Não herdar segredos de conectores/credenciais/Cloud do ambiente pai.
    inherited = ("PATH", "PYTHONPATH", "LANG", "LC_ALL", "PYTHONIOENCODING")
    env = {k: os.environ[k] for k in inherited if k in os.environ}
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    env["PYTHONNOUSERSITE"] = "1"
    proc = subprocess.Popen(
        args, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        text=True, encoding="utf-8", errors="replace",
        env=env, preexec_fn=_limites, start_new_session=True,
    )
    try:
        stdout, stderr = proc.communicate(timeout=timeout_s)
    except subprocess.TimeoutExpired as exc:
        try:
            os.killpg(proc.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        proc.communicate()
        raise ErroIsolamentoConab("worker atingiu timeout e foi encerrado") from exc
    # Truncar logs do retorno; não replicar payloads arbitrários em memória.
    return {
        "estado": "WORKER_ENCERRADO",
        "exit_code": proc.returncode,
        "stdout": stdout[-4096:],
        "stderr": stderr[-4096:],
        "timeout_s": timeout_s,
        "limites_aplicados": True,
        "isolamento_de_rede_aplicado": False,
        "habilita_publicacao": False,
        "habilita_treino": False,
        "habilita_backtest": False,
    }


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        description="Inspeção CONAB em worker Linux com limites de recursos"
    )
    parser.add_argument("--manifest", required=True)
    parser.add_argument("--base-dir", required=True)
    parser.add_argument("--out", required=True)
    parser.add_argument("--sqlite")
    parser.add_argument("--timeout", type=int, default=75)
    args = parser.parse_args(argv)
    try:
        result = executar_worker_conab(
            manifesto=args.manifest, base_dir=args.base_dir, saida=args.out,
            sqlite=args.sqlite, timeout_s=args.timeout,
        )
    except (ErroIsolamentoConab, OSError) as exc:
        print(f"WORKER REJEITADO: {exc}", file=sys.stderr)
        return 3
    if result["stdout"]:
        print(result["stdout"], end="")
    if result["stderr"]:
        print(result["stderr"], end="", file=sys.stderr)
    return result["exit_code"] if result["exit_code"] in (0, 2, 3) else 3


if __name__ == "__main__":
    raise SystemExit(main())
