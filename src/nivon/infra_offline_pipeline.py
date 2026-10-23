"""Pipeline NIVON de homologação: três jobs entre dois workers, sem fontes externas.

Prepare → execute (StatsForecast real) → verify → backup/restore. Nunca roda
coletores, agendadores, WhatsApp, IAM ou publica. Recuperação de crash somente
mediante fase explícita e após prova de ausência de artefato concluído.
"""
from __future__ import annotations

import argparse
from contextlib import closing
from datetime import timedelta
import hashlib
import json
import os
from pathlib import Path
import re
import stat

from .backup_sqlite import criar_backup, restaurar_backup, _sha256_stream
from .infra_job_ledger import (
    ErroJob, _instante, _iso, abrir_ledger, registrar, reservar,
    finalizar, reconciliar_vencidos, resumo,
)
from .infra_analytics_probe import validar_previsao

STAMP = "2026-10-20T16:30:00-03:00"
DUE = _iso(_instante(STAMP))
AT_RUN = _iso(_instante(STAMP) + timedelta(seconds=1))
AT_RECOVER = _iso(_instante(STAMP) + timedelta(seconds=180))
JOB_KEYS = tuple("TEST_SYNTHETIC_SERIE_" + x for x in ("AAA", "BBB", "CCC"))
SHA = re.compile(r"[0-9a-f]{64}\Z")
FLAGS = ("NIVON_RUNTIME_ENABLED", "NIVON_BACKUP_ENABLED",
         "NIVON_COLLECTORS_ENABLED", "NIVON_PUBLICATION_ENABLED")


class PipelineBlocked(ValueError):
    pass


def _private(folder: str | None) -> Path:
    if not isinstance(folder, str) or not folder.startswith("/"):
        raise PipelineBlocked("diretório privado absoluto obrigatório")
    p = Path(folder)
    if ".." in p.parts or p.is_symlink() or not p.is_dir():
        raise PipelineBlocked("diretório privado inválido")
    info = p.stat()
    if (info.st_uid != os.getuid() or stat.S_IMODE(info.st_mode) & 0o077):
        raise PipelineBlocked("diretório de estado deve pertencer ao UID e ser 0700")
    return p


def _dir(parent: Path, name: str) -> Path:
    p = parent / name
    if not p.exists():
        p.mkdir(mode=0o700)
    if p.is_symlink() or not p.is_dir() or p.stat().st_uid != os.getuid():
        raise PipelineBlocked("subdiretório inválido")
    if stat.S_IMODE(p.stat().st_mode) != 0o700:
        raise PipelineBlocked("subdiretório deve ser 0700")
    return p


def _bytes(obj: dict) -> bytes:
    return (json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
            + "\n").encode("ascii")


def _digest(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _write_once(path: Path, raw: bytes) -> bool:
    if len(raw) > 32_768 or not raw:
        raise PipelineBlocked("artefato sintético fora do limite")
    try:
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL |
                     getattr(os, "O_NOFOLLOW", 0), 0o600)
    except FileExistsError:
        return _read(path) == raw
    with os.fdopen(fd, "wb") as stream:
        stream.write(raw)
        stream.flush()
        os.fsync(stream.fileno())
    return True


def _read(path: Path) -> bytes:
    if path.is_symlink() or not path.is_file():
        raise PipelineBlocked("artefato não regular")
    st = path.stat()
    if st.st_uid != os.getuid() or stat.S_IMODE(st.st_mode) & 0o077 or st.st_size > 32_768:
        raise PipelineBlocked("artefato fora do limite ou inseguro")
    return path.read_bytes()


def _input(key: str) -> bytes:
    idx = JOB_KEYS.index(key)
    return _bytes({"schema": "nivon.synthetic.series.v1", "job_key": key,
                   "values": [float(i + idx) for i in range(1, 9)],
                   "due_utc": DUE})


def _out(key: str, forecast: list[object]) -> bytes:
    return _bytes({"schema": "nivon.synthetic.forecast.v1", "job_key": key,
                   "due_utc": DUE, "forecast": forecast})


def _forecast(raw: bytes, key: str) -> list[float]:
    # Importação tardia mantém a fase producer compatível com Alpine stdlib.
    import pandas as pd
    from statsforecast import StatsForecast
    from statsforecast.models import Naive

    payload = json.loads(raw)
    if (payload.get("schema") != "nivon.synthetic.series.v1"
        or payload.get("job_key") != key
        or raw != _input(key)):
        raise PipelineBlocked("contrato de dados sintéticos divergente")
    vals = payload["values"]
    data = pd.DataFrame({
        "unique_id": [key] * 8,
        "ds": pd.date_range("2026-01-01", periods=8, freq="D"),
        "y": vals,
    })
    fc = StatsForecast(models=[Naive()], freq="D", n_jobs=1).forecast(df=data, h=2)
    values = [float(v) for v in fc["Naive"].tolist()]
    validar_previsao(values, expected=float(vals[-1]))
    if len(fc) != 2 or fc["unique_id"].tolist() != [key] * 2:
        raise PipelineBlocked("horizonte de previsão divergente")
    return values


def _verify_files(root: Path, db) -> int:
    ins, outs = _dir(root, "inputs"), _dir(root, "outputs")
    if sorted(p.name for p in ins.iterdir()) != sorted(k + ".json" for k in JOB_KEYS):
        raise PipelineBlocked("conjunto de entradas incompleto ou inesperado")
    if sorted(p.name for p in outs.iterdir()) != sorted(k + ".json" for k in JOB_KEYS):
        raise PipelineBlocked("conjunto de saídas incompleto ou inesperado")
    for key in JOB_KEYS:
        row = db.execute("SELECT * FROM nivon_job WHERE job_key=? AND due_utc=?",
                         (key, DUE)).fetchone()
        if not row or row["status"] != "SUCCEEDED" or row["attempts"] < 1:
            raise PipelineBlocked("ledger possui execução não concluída")
        inp = _read(ins / (key + ".json"))
        output = _read(outs / (key + ".json"))
        if _digest(inp) != row["input_sha256"] or inp != _input(key):
            raise PipelineBlocked("SHA-256 de entrada ou conteúdo divergente")
        if _digest(output) != row["output_sha256"]:
            raise PipelineBlocked("SHA-256 da saída divergente")
        result = json.loads(output)
        index = JOB_KEYS.index(key)
        expected = 8.0 + index
        if (result.get("job_key") != key or
            result.get("due_utc") != DUE or
            result.get("schema") != "nivon.synthetic.forecast.v1"):
            raise PipelineBlocked("identidade da saída inválida")
        validar_previsao(result["forecast"], expected=expected)
    count = db.execute("SELECT COUNT(*) FROM nivon_job").fetchone()[0]
    if count != len(JOB_KEYS):
        raise PipelineBlocked("jobs adicionais não esperados")
    return count


def _prepare(root: Path) -> dict:
    ins = _dir(root, "inputs")
    _dir(root, "outputs")
    with closing(abrir_ledger(root / "jobs.sqlite")) as db:
        created = 0
        for key in JOB_KEYS:
            raw = _input(key)
            if not _write_once(ins / (key + ".json"), raw):
                raise PipelineBlocked("entrada existente divergente")
            created += int(registrar(db, chave=key, vencimento=DUE,
                                    input_sha256=_digest(raw), registrado_em=DUE)["novo"])
        return {"created": created, "jobs": sum(resumo(db)["contagens"].values())}


def _process(root: Path, *, interrupt: bool) -> dict:
    ins, outs = _dir(root, "inputs"), _dir(root, "outputs")
    with closing(abrir_ledger(root / "jobs.sqlite")) as db:
        newly = 0
        for key in JOB_KEYS:
            row = db.execute("SELECT * FROM nivon_job WHERE job_key=? AND due_utc=?",
                             (key,DUE)).fetchone()
            if not row:
                raise PipelineBlocked("job não registrado")
            if row["status"] == "SUCCEEDED":
                continue
            if row["status"] != "READY":
                raise PipelineBlocked("job pendente de reconciliação manual")
            raw = _read(ins / (key + ".json"))
            if _digest(raw) != row["input_sha256"] or raw != _input(key):
                raise PipelineBlocked("entrada alterada")
            # Em reexecução, o instante nunca retrocede após a reconciliação.
            now = _iso(max(_instante(AT_RECOVER),
                           _instante(row["updated_utc"]) + timedelta(seconds=1)))
            lease = reservar(db, chave=key, vencimento=DUE, agora=now,
                             lease_segundos=120)
            if not lease["reservado"]:
                raise PipelineBlocked("reserva não obtida")
            if interrupt:
                return {"interrupted_after_lease": True, "requires_reconciliation": True}
            result = _out(key, _forecast(raw, key))
            if not _write_once(outs / (key + ".json"), result):
                raise PipelineBlocked("saída imutável divergiu")
            done = finalizar(db, chave=key, vencimento=DUE,
                             token=lease["token"], agora=now,
                             sucesso=True, output_sha256=_digest(result))
            if done["estado"] != "SUCCEEDED":
                raise PipelineBlocked("finalização do ledger falhou")
            newly += 1
        return {"processed": newly, "jobs": len(JOB_KEYS)}


def _reconcile(root: Path) -> dict:
    outs = _dir(root, "outputs")
    with closing(abrir_ledger(root / "jobs.sqlite")) as db:
        expired_at = _iso(_instante(STAMP) + timedelta(seconds=310))
        expired = reconciliar_vencidos(db, agora=expired_at)
        changed = 0
        for key in JOB_KEYS:
            row = db.execute("SELECT status FROM nivon_job WHERE job_key=? AND due_utc=?",
                             (key,DUE)).fetchone()
            if row and row["status"] == "UNCERTAIN":
                if (outs / (key + ".json")).exists():
                    raise PipelineBlocked("saída existente exige revisão humana")
                # Somente TEST_SYNTHETIC_*, sem chamadas externas, output ausente
                # e com reconciliação explícita; nunca aplica a jobs reais.
                db.execute("BEGIN IMMEDIATE")
                try:
                    db.execute("""UPDATE nivon_job SET status='READY',updated_utc=?
                                  WHERE job_key=? AND due_utc=? AND status='UNCERTAIN'""",
                               (expired_at,key,DUE))
                    db.execute("""INSERT INTO nivon_job_event
                                  (job_key,due_utc,observed_utc,event)
                                  VALUES (?,?,?,'EXPLICIT_SYNTHETIC_REQUEUE')""",
                               (key,DUE,expired_at))
                    db.execute("COMMIT")
                except BaseException:
                    db.execute("ROLLBACK")
                    raise
                changed += 1
        return {"expired": expired, "explicit_requeued": changed}


def _backup(root: Path, backup: Path) -> dict:
    with closing(abrir_ledger(root / "jobs.sqlite")) as db:
        _verify_files(root, db)
        _dir(backup, "inputs")
        _dir(backup, "outputs")
        snap = criar_backup(db, backup / "jobs.sqlite")
        items = {"jobs.sqlite": snap["sha256"]}
        for kind in ("inputs", "outputs"):
            for key in JOB_KEYS:
                name = kind + "/" + key + ".json"
                raw = _read(root / name)
                if not _write_once(backup / name, raw):
                    raise PipelineBlocked("backup parcial/existente")
                items[name] = _digest(raw)
        manifest = _bytes({"schema": "nivon.synthetic.backup.v1", "files": items,
                           "job_count": len(JOB_KEYS), "remote": False})
        if not _write_once(backup / "manifest.json", manifest):
            raise PipelineBlocked("manifesto divergente")
        return {"snapshot_sha256": snap["sha256"], "files": len(items),
                "remote_backup_verified": False}


def _restore(root: Path, backup: Path) -> dict:
    if tuple(root.iterdir()):
        raise PipelineBlocked("destino de restauração deve estar vazio")
    manifest = json.loads(_read(backup / "manifest.json"))
    if (manifest.get("schema") != "nivon.synthetic.backup.v1"
        or manifest.get("job_count") != len(JOB_KEYS)):
        raise PipelineBlocked("manifesto não homologado")
    expected = {"jobs.sqlite"} | {
        kind + "/" + key + ".json" for kind in ("inputs", "outputs") for key in JOB_KEYS
    }
    hashes = manifest.get("files")
    if not isinstance(hashes, dict) or set(hashes) != expected:
        raise PipelineBlocked("arquivo de backup faltante ou inesperado")
    for name in sorted(expected):
        if not isinstance(hashes[name], str) or not SHA.fullmatch(hashes[name]):
            raise PipelineBlocked("digest de backup inválido")
        if name == "jobs.sqlite":
            if _sha256_stream(backup / name) != hashes[name]:
                raise PipelineBlocked("backup SQLite divergente")
        elif _digest(_read(backup / name)) != hashes[name]:
            raise PipelineBlocked("artefato de backup adulterado")
    restaurar_backup(backup / "jobs.sqlite", root / "jobs.sqlite",
                     sha256_esperado=hashes["jobs.sqlite"])
    for kind in ("inputs", "outputs"):
        _dir(root, kind)
        for key in JOB_KEYS:
            name = kind + "/" + key + ".json"
            if not _write_once(root / name, _read(backup / name)):
                raise PipelineBlocked("arquivo restaurado divergente")
    with closing(abrir_ledger(root / "jobs.sqlite")) as db:
        return {"restored_jobs": _verify_files(root, db),
                "verified": True, "remote_backup_verified": False}


def executar(stage: str, *, root: str, backup_root: str | None, interrupt: bool) -> dict:
    if stage not in ("prepare", "process", "reconcile", "verify", "backup", "restore"):
        raise PipelineBlocked("fase não permitida")
    if any(os.environ.get(k, "false") != "false" for k in FLAGS):
        raise PipelineBlocked("flag de execução real habilitada")
    base = _private(root)
    if interrupt and stage != "process":
        raise PipelineBlocked("falha simulada só no processamento")
    extra = _private(backup_root) if stage in ("backup","restore") else None
    if stage == "prepare":
        result = _prepare(base)
    elif stage == "process":
        result = _process(base, interrupt=interrupt)
    elif stage == "reconcile":
        result = _reconcile(base)
    elif stage == "verify":
        with closing(abrir_ledger(base / "jobs.sqlite")) as db:
            result = {"verified_jobs": _verify_files(base, db)}
    elif stage == "backup":
        result = _backup(base, extra)
    else:
        result = _restore(base, extra)
    return {"schema": "nivon.infra.pipeline_batch.v1", "stage": stage,
            "mode": "SYNTHETIC_OFFLINE", "production_authorized": False,
            "data_sources_called": 0, "publications": 0, **result}


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Batch NIVON apenas sintético offline")
    p.add_argument("--stage", required=True,
                   choices=("prepare", "process", "reconcile", "verify", "backup", "restore"))
    p.add_argument("--interrupt-after-lease", action="store_true")
    args = p.parse_args(argv)
    try:
        result = executar(args.stage, root=os.environ.get("NIVON_OFFLINE_STATE_DIR", ""),
                          backup_root=os.environ.get("NIVON_OFFLINE_BACKUP_DIR"),
                          interrupt=args.interrupt_after_lease)
    except (OSError, ValueError, ErroJob):
        print(json.dumps({"status": "BLOCKED", "production_authorized": False}))
        return 2
    print(json.dumps(result, sort_keys=True))
    return 3 if result.get("interrupted_after_lease") else 0


if __name__ == "__main__":
    raise SystemExit(main())
