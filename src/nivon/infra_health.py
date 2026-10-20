"""Diagnóstico PASSIVO do NIVON: estado cloud, backup e ledger local.

Não abre portas, não inicia scheduler, não cria arquivos, não consulta rede.
Um resultado sintético bem-sucedido nunca é apresentado como saúde de produção.
"""
from __future__ import annotations

import argparse
import json
import os
import sqlite3
import stat
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import quote

from .infra_preflight import carregar_inventario, validar_inventario, InfraError
from .infra_job_ledger import _instante, ErroJob


class ErroSaude(ValueError):
    pass


def _abrir_leitura_ledger(caminho: str | Path) -> sqlite3.Connection:
    p = Path(caminho)
    if p.is_symlink() or not p.is_file():
        raise ErroSaude("ledger ausente ou caminho simbólico")
    par = p.parent
    if par.is_symlink() or not par.is_dir():
        raise ErroSaude("diretório de ledger ausente ou simbólico")
    dados, pasta = p.stat(), par.stat()
    if not stat.S_ISREG(dados.st_mode) or dados.st_uid != os.getuid() or stat.S_IMODE(dados.st_mode) & 0o077:
        raise ErroSaude("ledger sem propriedade/permissões privadas")
    if pasta.st_uid != os.getuid() or stat.S_IMODE(pasta.st_mode) & 0o077:
        raise ErroSaude("pasta do ledger não é privada")
    if not 0 < dados.st_size <= 1_000_000_000:
        raise ErroSaude("ledger vazio ou acima do limite de inspeção")
    uri = "file:" + quote(str(p.absolute()), safe="/") + "?mode=ro"
    try:
        conn = sqlite3.connect(uri, uri=True, timeout=2)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA query_only=ON")
        tables = {r[0] for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'")}
        if not {"nivon_job", "nivon_job_event"}.issubset(tables):
            raise ErroSaude("schema do ledger não verificado")
        return conn
    except (sqlite3.Error, ErroSaude) as exc:
        conn.close()
        raise ErroSaude("ledger não pode ser inspecionado com segurança") from exc


def verificar_saude(*, inventario: dict, agora: str,
                   ledger: str | Path | None = None) -> dict:
    # Exige o mesmo gate fail-closed de infraestrutura: não concede liberação.
    base = validar_inventario(inventario)
    instante = _instante(agora).isoformat(timespec="microseconds")
    st = inventario["storage_policy"]
    blocked = sorted(k for k, v in inventario["release_gates"].items() if not v)
    avisos = ["CLOUD_NOT_VERIFIED", "SERVICES_OFFLINE", "SCHEDULER_NOT_RUNNING"]
    if not st["encrypted_remote_backup_verified"] or not st["restore_in_separate_environment_verified"]:
        avisos.append("REMOTE_RECOVERY_NOT_VERIFIED")
    ledger_dados = {"estado": "NOT_CONFIGURED", "jobs": None,
                    "incertos": None, "leases_vencidos": None,
                    "ultimo_sucesso": None}
    if ledger is not None:
        with _abrir_leitura_ledger(ledger) as conn:
            expected = {"READY", "RUNNING", "SUCCEEDED", "FAILED", "UNCERTAIN"}
            rows = conn.execute("SELECT status, count(*) n FROM nivon_job GROUP BY status").fetchall()
            if any(r["status"] not in expected for r in rows):
                raise ErroSaude("ledger possui status inválido")
            counts = {s: 0 for s in expected}
            counts.update({r["status"]: r["n"] for r in rows})
            expired = conn.execute("""SELECT count(*) FROM nivon_job
                  WHERE status='RUNNING' AND lease_until_utc<=?""",
                  (instante,)).fetchone()[0]
            last = conn.execute("""SELECT MAX(updated_utc) FROM nivon_job
                  WHERE status='SUCCEEDED'""").fetchone()[0]
            ledger_dados = {
                "estado": "SYNTHETIC_OFFLINE_ONLY",
                "jobs": sum(counts.values()),
                "incertos": counts["UNCERTAIN"],
                "leases_vencidos": expired,
                "ultimo_sucesso": last,
            }
        if ledger_dados["incertos"]:
            avisos.append("UNCERTAIN_JOBS_NEED_MANUAL_RECONCILIATION")
        if ledger_dados["leases_vencidos"]:
            avisos.append("EXPIRED_RUNNING_LEASES_NEED_RECONCILIATION")
    else:
        avisos.append("JOB_LEDGER_NOT_CONFIGURED")
    return {
        "sistema": "NIVON",
        "modo": "PASSIVE_LOCAL_AUDIT",
        "avaliado_em_utc": instante,
        "estado": "NOT_OPERATIONAL",
        "producao_aprovada": False,
        "coleta_real": False,
        "envio_whatsapp": False,
        "cloud_comprovada": base["cloud_confirmada"],
        "componentes_catalogados": base["componentes"],
        "gates_bloqueados": len(blocked),
        "ledger": ledger_dados,
        "avisos": sorted(avisos),
        "nota": "verificação de contrato e SQLite sintético; não é sonda de serviço cloud",
    }


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description="Diagnóstico NIVON offline e somente leitura")
    p.add_argument("--manifest", help="inventário opcional")
    p.add_argument("--ledger", help="somente arquivo de ledger sintético privado")
    p.add_argument("--agora", help="ISO com fuso, para ensaios reprodutíveis")
    p.add_argument("--require-operational", action="store_true",
                   help="retorna 3 quando infraestrutura não está homologada")
    args = p.parse_args(argv)
    try:
        now = args.agora or datetime.now(timezone.utc).isoformat()
        result = verificar_saude(inventario=carregar_inventario(args.manifest),
                                agora=now, ledger=args.ledger)
        print(json.dumps(result, ensure_ascii=False, sort_keys=True))
        return 3 if args.require_operational else 0
    except (OSError, ValueError, sqlite3.Error) as exc:
        print(json.dumps({"estado": "INVALID", "reason": str(exc)}, ensure_ascii=False))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
