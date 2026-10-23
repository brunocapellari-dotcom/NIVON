"""Controle durável OFFLINE de jobs sintéticos, sem coletar, agendar ou enviar.

A interface aceita EXCLUSIVAMENTE job TEST_SYNTHETIC_*; nenhuma integração
operacional é autorizada. Leases vencidos tornam-se INCERTOS, nunca retry
automático: uma ação externa pode ter ocorrido antes de um crash.
"""
from __future__ import annotations

import json
import os
import re
import secrets
import sqlite3
import stat
from datetime import datetime, timedelta, timezone
from pathlib import Path

_KEY = re.compile(r"TEST_SYNTHETIC_[A-Z0-9_]{3,70}\Z")
_SHA = re.compile(r"[0-9a-f]{64}\Z")
_STATES = ("READY", "RUNNING", "SUCCEEDED", "FAILED", "UNCERTAIN")


class ErroJob(ValueError):
    pass


def _instante(s: str) -> datetime:
    if not isinstance(s, str):
        raise ErroJob("instante ISO com fuso obrigatório")
    try:
        v = datetime.fromisoformat(s.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ErroJob("instante ISO inválido") from exc
    if v.tzinfo is None or v.utcoffset() is None:
        raise ErroJob("instante sem fuso")
    return v.astimezone(timezone.utc)


def _iso(d: datetime) -> str:
    return d.isoformat(timespec="microseconds")


def _seguro(path: Path) -> None:
    """Exige pasta privada e arquivo 0600, sem seguir links simbólicos.

    Pasta pai compartilhada (p.ex. /tmp) só é permitida se a pasta imediata
    do SQLite for restrita. Banco NÃO pode morar no repositório público.
    """
    par = path.parent
    if par.is_symlink() or not par.is_dir():
        raise ErroJob("diretório privado ausente ou simbólico")
    info = par.stat()
    if not stat.S_ISDIR(info.st_mode) or info.st_uid != os.getuid() or stat.S_IMODE(info.st_mode) & 0o077:
        raise ErroJob("diretório não pertence ao usuário ou permite acesso de grupo/terceiros")
    if path.is_symlink():
        raise ErroJob("arquivo SQLite simbólico")
    flags = os.O_CREAT | os.O_EXCL | os.O_WRONLY
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    try:
        fd = os.open(path, flags, 0o600)
    except FileExistsError:
        if not path.is_file() or path.is_symlink():
            raise ErroJob("arquivo SQLite não regular")
        fileinfo = path.stat()
        if fileinfo.st_uid != os.getuid() or stat.S_IMODE(fileinfo.st_mode) & 0o077:
            raise ErroJob("arquivo SQLite com permissões inseguras")
    else:
        os.close(fd)


def abrir_ledger(caminho: str | Path = ":memory:") -> sqlite3.Connection:
    """Abra banco somente em pasta privada 0700. Sem conexão externa."""
    if str(caminho) != ":memory:":
        _seguro(Path(caminho))
    db = sqlite3.connect(str(caminho), timeout=15, isolation_level=None)
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA foreign_keys=ON")
    db.execute("PRAGMA busy_timeout=15000")
    db.execute("PRAGMA synchronous=FULL")
    if str(caminho) != ":memory:":
        db.execute("PRAGMA journal_mode=WAL")
    db.executescript("""
        CREATE TABLE IF NOT EXISTS nivon_job(
            job_key TEXT NOT NULL, due_utc TEXT NOT NULL,
            input_sha256 TEXT NOT NULL,
            mode TEXT NOT NULL CHECK(mode='SYNTHETIC_OFFLINE'),
            status TEXT NOT NULL CHECK(status IN
               ('READY','RUNNING','SUCCEEDED','FAILED','UNCERTAIN')),
            token TEXT, lease_until_utc TEXT, attempts INTEGER NOT NULL DEFAULT 0,
            output_sha256 TEXT, updated_utc TEXT NOT NULL,
            PRIMARY KEY(job_key,due_utc),
            CHECK(attempts >= 0)
        );
        CREATE TABLE IF NOT EXISTS nivon_job_event(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            job_key TEXT NOT NULL, due_utc TEXT NOT NULL,
            observed_utc TEXT NOT NULL, event TEXT NOT NULL,
            FOREIGN KEY(job_key,due_utc) REFERENCES nivon_job(job_key,due_utc)
        );
        CREATE INDEX IF NOT EXISTS idx_job_status ON nivon_job(status,due_utc);
    """)
    return db


def _transacao(db: sqlite3.Connection, fn):
    db.execute("BEGIN IMMEDIATE")
    try:
        result = fn()
        db.execute("COMMIT")
        return result
    except BaseException:
        db.execute("ROLLBACK")
        raise


def registrar(db: sqlite3.Connection, *, chave: str, vencimento: str,
             input_sha256: str, registrado_em: str) -> dict:
    if not isinstance(chave, str) or not _KEY.fullmatch(chave):
        raise ErroJob("somente chaves TEST_SYNTHETIC_* são permitidas")
    if not isinstance(input_sha256, str) or not _SHA.fullmatch(input_sha256):
        raise ErroJob("SHA-256 do contrato sintético inválido")
    due, now = _iso(_instante(vencimento)), _iso(_instante(registrado_em))

    def op():
        row = db.execute("SELECT * FROM nivon_job WHERE job_key=? AND due_utc=?",
                         (chave, due)).fetchone()
        if row:
            if row["input_sha256"] != input_sha256 or row["mode"] != "SYNTHETIC_OFFLINE":
                raise ErroJob("idempotência: job existente com entrada divergente")
            return {"novo": False, "estado": row["status"]}
        db.execute("""INSERT INTO nivon_job
           (job_key,due_utc,input_sha256,mode,status,updated_utc)
           VALUES (?,?,?,'SYNTHETIC_OFFLINE','READY',?)""",
           (chave, due, input_sha256, now))
        db.execute("""INSERT INTO nivon_job_event
          (job_key,due_utc,observed_utc,event) VALUES (?,?,?,'REGISTERED')""",
          (chave, due, now))
        return {"novo": True, "estado": "READY"}
    return _transacao(db, op)


def reservar(db: sqlite3.Connection, *, chave: str, vencimento: str,
            agora: str, lease_segundos: int = 120) -> dict:
    if type(lease_segundos) is not int or not 10 <= lease_segundos <= 3600:
        raise ErroJob("lease fora de 10..3600 segundos")
    due, now_dt = _iso(_instante(vencimento)), _instante(agora)
    now = _iso(now_dt)
    if now < due:
        raise ErroJob("job ainda não venceu")

    def op():
        row = db.execute("SELECT * FROM nivon_job WHERE job_key=? AND due_utc=?",
                         (chave, due)).fetchone()
        if not row:
            raise ErroJob("job inexistente")
        if row["status"] == "RUNNING" and row["lease_until_utc"] <= now:
            db.execute("""UPDATE nivon_job SET status='UNCERTAIN',
                token=NULL,lease_until_utc=NULL,updated_utc=?
                WHERE job_key=? AND due_utc=?""", (now,chave,due))
            db.execute("""INSERT INTO nivon_job_event
                (job_key,due_utc,observed_utc,event)
                VALUES (?,?,?,'LEASE_EXPIRED_UNCERTAIN')""", (chave,due,now))
            return {"reservado": False, "estado": "UNCERTAIN"}
        if row["status"] != "READY":
            return {"reservado": False, "estado": row["status"]}
        token = secrets.token_hex(24)
        deadline = _iso(now_dt + timedelta(seconds=lease_segundos))
        db.execute("""UPDATE nivon_job SET status='RUNNING',token=?,
          lease_until_utc=?,attempts=attempts+1,updated_utc=?
          WHERE job_key=? AND due_utc=? AND status='READY'""",
          (token,deadline,now,chave,due))
        db.execute("""INSERT INTO nivon_job_event
          (job_key,due_utc,observed_utc,event) VALUES (?,?,?,'STARTED')""",
          (chave,due,now))
        return {"reservado": True, "estado": "RUNNING",
                "token": token, "lease_until_utc": deadline}
    return _transacao(db, op)


def finalizar(db: sqlite3.Connection, *, chave: str, vencimento: str, token: str,
              agora: str, sucesso: bool, output_sha256: str | None = None) -> dict:
    if not isinstance(token,str) or not re.fullmatch(r"[0-9a-f]{48}",token):
        raise ErroJob("token de lease inválido")
    if type(sucesso) is not bool:
        raise ErroJob("sucesso deve ser booleano")
    if sucesso and (not isinstance(output_sha256,str) or not _SHA.fullmatch(output_sha256)):
        raise ErroJob("sucesso exige hash verificável do resultado")
    if not sucesso and output_sha256 is not None:
        raise ErroJob("falha não deve fingir saída válida")
    due, now = _iso(_instante(vencimento)), _iso(_instante(agora))

    def op():
        row = db.execute("SELECT * FROM nivon_job WHERE job_key=? AND due_utc=?",
                         (chave,due)).fetchone()
        if not row or row["status"] != "RUNNING" or row["token"] != token:
            raise ErroJob("lease não pertence a esta execução")
        if now >= row["lease_until_utc"]:
            db.execute("""UPDATE nivon_job SET status='UNCERTAIN',
                token=NULL,lease_until_utc=NULL,updated_utc=?
                WHERE job_key=? AND due_utc=?""", (now,chave,due))
            db.execute("""INSERT INTO nivon_job_event
                (job_key,due_utc,observed_utc,event)
                VALUES (?,?,?,'FINISH_AFTER_LEASE_UNCERTAIN')""", (chave,due,now))
            return {"estado": "UNCERTAIN", "publicar": False}
        state = "SUCCEEDED" if sucesso else "FAILED"
        db.execute("""UPDATE nivon_job SET status=?,token=NULL,
            lease_until_utc=NULL,output_sha256=?,updated_utc=?
            WHERE job_key=? AND due_utc=?""",
            (state,output_sha256,now,chave,due))
        db.execute("""INSERT INTO nivon_job_event
          (job_key,due_utc,observed_utc,event) VALUES (?,?,?,?)""",
          (chave,due,now,state))
        return {"estado":state,"publicar":False}
    return _transacao(db, op)


def reconciliar_vencidos(db: sqlite3.Connection, *, agora: str) -> int:
    now = _iso(_instante(agora))

    def op():
        rows = db.execute("""SELECT job_key,due_utc FROM nivon_job
          WHERE status='RUNNING' AND lease_until_utc<=?""", (now,)).fetchall()
        for r in rows:
            db.execute("""UPDATE nivon_job SET status='UNCERTAIN',token=NULL,
              lease_until_utc=NULL,updated_utc=? WHERE job_key=? AND due_utc=?""",
              (now,r["job_key"],r["due_utc"]))
            db.execute("""INSERT INTO nivon_job_event
              (job_key,due_utc,observed_utc,event)
              VALUES (?,?,?,'LEASE_EXPIRED_UNCERTAIN')""",
              (r["job_key"],r["due_utc"],now))
        return len(rows)
    return _transacao(db, op)


def resumo(db: sqlite3.Connection) -> dict:
    counts = {v:0 for v in _STATES}
    counts.update({r["status"]:r["n"] for r in db.execute(
        "SELECT status,COUNT(*) n FROM nivon_job GROUP BY status")})
    return {"modo":"SYNTHETIC_OFFLINE","publicacao":False,
            "agendador_ativo":False,"contagens":counts,
            "incertos_exigem_reconciliacao":counts["UNCERTAIN"]}


def main(argv=None) -> int:
    import argparse
    p = argparse.ArgumentParser(description="Ledger offline NIVON; sem jobs reais")
    p.add_argument("--status", action="store_true", help="somente banco em memória vazio")
    args = p.parse_args(argv)
    if not args.status:
        p.error("somente --status é permitido")
    with abrir_ledger() as db:
        print(json.dumps(resumo(db),ensure_ascii=False,sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
