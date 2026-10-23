"""Ensaio E2E da execução NIVON, exclusivamente sintético e sem rede.

Uma chamada explícita exercita registrar -> reservar -> computar hash puro ->
finalizar -> reiniciar. Não registra datasets reais, não roda schedule, não
cria serviços, não envia mensagens e nunca publica conteúdo.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path

from .infra_job_ledger import (
    ErroJob, _instante, abrir_ledger, registrar, reservar, finalizar, resumo
)

CHAVE = "TEST_SYNTHETIC_SMOKE_PIPELINE"
ENTRADA = hashlib.sha256(b"NIVON_INFRA_SMOKE_V1_OFFLINE").hexdigest()


def executar_smoke(*, banco: str | Path = ":memory:", instante: str) -> dict:
    now = _instante(instante).isoformat(timespec="microseconds")
    with closing(abrir_ledger(banco)) as db:
        reg = registrar(db, chave=CHAVE, vencimento=now,
                        input_sha256=ENTRADA, registrado_em=now)
        lease = reservar(db, chave=CHAVE, vencimento=now, agora=now,
                         lease_segundos=120)
        resultado = lease["estado"]
        if lease["reservado"]:
            # Processamento intencionalmente puro: sem fonte real ou IO externo.
            saida = hashlib.sha256(("CONTRATO:" + ENTRADA).encode("ascii")).hexdigest()
            final = finalizar(db, chave=CHAVE, vencimento=now,
                              token=lease["token"], agora=now,
                              sucesso=True, output_sha256=saida)
            resultado = final["estado"]
        counts = resumo(db)
        eventos = db.execute("""SELECT COUNT(*) FROM nivon_job_event
             WHERE job_key=? AND due_utc=?""", (CHAVE,now)).fetchone()[0]
        return {
            "tipo":"SMOKE_E2E_SINTETICO_OFFLINE",
            "estado":resultado,
            "registro_novo":reg["novo"],
            "execucao_nova":lease["reservado"],
            "eventos":eventos,
            "publicacao":False,
            "coleta_real":False,
            "agendamento":False,
            "backup_remoto_verificado":False,
            "contagens":counts["contagens"]
        }


def main(argv=None) -> int:
    parser=argparse.ArgumentParser(description="NIVON: E2E sintético local")
    parser.add_argument("--db",default=":memory:",
                        help="somente memória ou arquivo em pasta privada 0700")
    parser.add_argument("--instante",help="timestamp ISO com timezone, opcional")
    args=parser.parse_args(argv)
    agora=args.instante or datetime.now(timezone.utc).isoformat()
    try:
        res=executar_smoke(banco=args.db, instante=agora)
        print(json.dumps(res,ensure_ascii=False,sort_keys=True))
        return 0 if res["estado"]=="SUCCEEDED" else 3
    except (OSError,ErroJob) as exc:
        print(json.dumps({"estado":"BLOQUEADO","motivo":str(exc)},ensure_ascii=False))
        return 2


if __name__=="__main__":
    raise SystemExit(main())
