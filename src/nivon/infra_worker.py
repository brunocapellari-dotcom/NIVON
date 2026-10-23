"""Entrypoint de worker NIVON — exclusivo para homologação sintética offline.

Pode rodar em contêiner read-only com diretório privado montado para estado.
Não executa fontes externas, cron, API, IAM, publish ou WhatsApp.
"""
from __future__ import annotations

import argparse
import json
import os
from datetime import datetime
from pathlib import Path

from .infra_preflight import InfraError, carregar_inventario, validar_inventario
from .infra_smoke import executar_smoke
from .infra_job_ledger import ErroJob


class ErroWorker(ValueError):
    pass


def executar_worker(
    *,
    modo: str,
    ambiente: dict[str, str],
    agora: str | None = None,
    inventario: dict | None = None,
) -> dict:
    """Contrato de execução explicitamente fechado para qualquer ação real."""
    if modo not in ("self-check", "synthetic-once"):
        raise ErroWorker("modo de execução não permitido")
    for key in ("NIVON_RUNTIME_ENABLED", "NIVON_BACKUP_ENABLED",
                "NIVON_COLLECTORS_ENABLED", "NIVON_PUBLICATION_ENABLED"):
        if ambiente.get(key, "false") != "false":
            raise ErroWorker("flag de execução externa proibida: " + key)
    status = validar_inventario(inventario if inventario is not None else carregar_inventario())
    if modo == "self-check":
        if agora is not None:
            raise ErroWorker("self-check não aceita horário de coleta")
        return {
            "mode": modo,
            "status": "OFFLINE_WORKER_CHECK_OK_NOT_OPERATIONAL",
            "live": False,
            "cloud_confirmed": False,
            "collector_count": 0,
            "storage_mutated": False,
            "preflight": status["status"],
        }
    if not isinstance(agora, str) or not agora:
        raise ErroWorker("synthetic-once exige --instante com fuso")
    path_str = ambiente.get("NIVON_OFFLINE_STATE_DIR")
    if not isinstance(path_str, str) or not path_str.startswith("/"):
        raise ErroWorker("NIVON_OFFLINE_STATE_DIR deve ser diretório privado absoluto")
    root = Path(path_str)
    if root.is_symlink() or not root.is_dir() or ".." in root.parts:
        raise ErroWorker("diretório privado de estado ausente ou inseguro")
    if not root.is_absolute():
        raise ErroWorker("diretório de estado deve ser absoluto")
    # O ledger valida ownership, modo 0700 do diretório e modo 0600 do SQLite.
    info = executar_smoke(banco=root / "jobs.sqlite", instante=agora)
    return {
        "mode": modo,
        "status": info["estado"],
        "live": False,
        "cloud_confirmed": False,
        "collector_count": 0,
        "publishes": False,
        "sends_whatsapp": False,
        "state_written": bool(info["execucao_nova"]),
        "job_count": sum(info["contagens"].values()),
        "uncertain_count": info["contagens"]["UNCERTAIN"],
    }


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Worker NIVON somente offline")
    p.add_argument("--mode", choices=["self-check", "synthetic-once"],
                   default="self-check")
    p.add_argument("--instante", help="ISO 8601 com fuso; somente synthetic-once")
    args = p.parse_args(argv)
    try:
        result = executar_worker(modo=args.mode, ambiente=dict(os.environ),
                                  agora=args.instante)
        print(json.dumps(result, sort_keys=True, ensure_ascii=False))
        return 0 if result["status"] in ("SUCCEEDED",
                                      "OFFLINE_WORKER_CHECK_OK_NOT_OPERATIONAL") else 3
    except (OSError, ValueError, InfraError, ErroJob) as exc:
        print(json.dumps({"status": "BLOCKED", "reason": str(exc)}, ensure_ascii=False))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
