"""Backup/restauração de ensaio dos dois SQLite CONAB: OFFLINE, sem migração.

Snapshot SQLite usa a API sqlite3.backup (consistente POR BANCO, inclusive WAL);
NÃO oferece atomicidade cruzada entre os dois bancos ou prova de fonte/RAW.
Saídas somente em pasta vazia e privada, nunca sobrescrevendo arquivos.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import sqlite3
import stat
from datetime import datetime, timezone
from contextlib import closing
from pathlib import Path
from urllib.parse import quote

from .conciliacao_progresso_stores import _verificar_esquemas

_SCHEMA = "NIVON_CONAB_BACKUP_V1"
_FILES = {"LEGADO": "legado.sqlite", "CANONICO": "canonico.sqlite"}
_TABLES = {
    "LEGADO": ("progresso_edicoes", "progresso_coletas", "progresso_observacoes"),
    "CANONICO": ("nivon_snapshots", "nivon_coletas", "nivon_conab_progresso"),
}
_MANIFEST = "backup_manifesto.json"
_RESTORE = "restauracao_verificada.json"
_MAX_MANIFEST = 100_000


class ErroBackupConab(ValueError):
    pass


def _path_file(value: str | Path) -> Path:
    p = Path(value)
    if p.is_symlink() or not p.is_file() or not p.is_absolute():
        raise ErroBackupConab("SQLite deve ser arquivo regular absoluto, sem symlink")
    return p


def _diretorio_privado_vazio(value: str | Path) -> Path:
    p = Path(value)
    if not p.is_absolute() or p.is_symlink() or not p.is_dir():
        raise ErroBackupConab("destino deve ser diretório já existente e absoluto, sem symlink")
    if os.name == "posix" and (stat.S_IMODE(p.stat().st_mode) & 0o077):
        raise ErroBackupConab("diretório de destino precisa ser privado (modo 0700)")
    if any(p.iterdir()):
        raise ErroBackupConab("destino não vazio: proibido sobrescrever")
    return p


def _readonly(path: Path) -> sqlite3.Connection:
    path = _path_file(path)
    uri = "file:" + quote(str(path.resolve()), safe="/") + "?mode=ro"
    try:
        db = sqlite3.connect(uri, uri=True, timeout=10)
        db.execute("PRAGMA query_only=ON")
    except sqlite3.Error as exc:
        raise ErroBackupConab("não foi possível abrir SQLite de origem somente leitura") from exc
    return db


def _verificar_integridade(db: sqlite3.Connection, store: str) -> dict:
    try:
        integrity = db.execute("PRAGMA integrity_check").fetchall()
        if integrity != [("ok",)]:
            raise ErroBackupConab("integridade SQLite inválida")
        violations = db.execute("PRAGMA foreign_key_check").fetchmany(1)
        if violations:
            raise ErroBackupConab("violações de chave estrangeira no SQLite")
        counts = {}
        for table in _TABLES[store]:
            qty = db.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
            if type(qty) is not int or qty < 0:
                raise ErroBackupConab("contagem SQLite inesperada")
            counts[table] = qty
        return counts
    except sqlite3.Error as exc:
        raise ErroBackupConab("falha de integridade/schema SQLite") from exc


def _sha(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as f:
        while True:
            chunk = f.read(1024 * 1024)
            if not chunk:
                break
            digest.update(chunk)
    return digest.hexdigest()


def _new_private_file(path: Path) -> None:
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    os.close(fd)


def _json_exclusivo(path: Path, value: dict) -> None:
    data = json.dumps(value, ensure_ascii=False, sort_keys=True,
                      indent=2, allow_nan=False)
    # Abrir em modo exclusivo: nunca sobrescrever arquivo pré-existente.
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(data)
            f.flush()
            os.fsync(f.fileno())
    except BaseException:
        path.unlink(missing_ok=True)
        raise


def _pairs_unique(pairs):
    out = {}
    for k,v in pairs:
        if k in out:
            raise ErroBackupConab("manifesto com chave JSON duplicada")
        out[k] = v
    return out


def _ler_manifesto(path: Path) -> dict:
    path = _path_file(path)
    if not 0 < path.stat().st_size <= _MAX_MANIFEST:
        raise ErroBackupConab("manifesto vazio ou grande")
    try:
        v = json.loads(path.read_text(encoding="utf-8"),
                       object_pairs_hook=_pairs_unique)
    except (UnicodeError, ValueError) as exc:
        raise ErroBackupConab("manifesto JSON inválido") from exc
    if (not isinstance(v, dict) or set(v) != {
            "schema","criado_utc","arquivos","consistencia_entre_bancos",
            "contem_raw_externo","direitos_validos_comprovados",
            "apto_migracao_producao"} or v["schema"] != _SCHEMA
            or v["consistencia_entre_bancos"] != "NAO_ATOMICA"
            or v["contem_raw_externo"] is not False
            or v["direitos_validos_comprovados"] is not False
            or v["apto_migracao_producao"] is not False):
        raise ErroBackupConab("contrato/gates do manifesto inválidos")
    try:
        dt = datetime.fromisoformat(v["criado_utc"])
        if dt.tzinfo is None or dt.utcoffset() is None:
            raise ValueError("sem fuso")
    except (ValueError, TypeError) as exc:
        raise ErroBackupConab("timestamp inválido no manifesto") from exc
    files = v["arquivos"]
    if not isinstance(files, dict) or set(files) != set(_FILES):
        raise ErroBackupConab("manifesto não tem exatamente os dois bancos")
    for store, data in files.items():
        if (not isinstance(data, dict) or set(data) != {
                "arquivo","sha256","bytes","linhas_por_tabela","capturado_inicio_utc",
                "capturado_fim_utc","integridade_sqlite"}):
            raise ErroBackupConab("campos da evidência do backup inválidos")
        if data["arquivo"] != _FILES[store] or data["integridade_sqlite"] != "ok":
            raise ErroBackupConab("arquivo ou integridade não correspondem ao contrato")
        h=data["sha256"]
        if (not isinstance(h,str) or len(h)!=64
                or any(c not in "0123456789abcdef" for c in h)):
            raise ErroBackupConab("hash de backup inválido")
        if type(data["bytes"]) is not int or data["bytes"] <= 0:
            raise ErroBackupConab("tamanho inválido do backup")
        counts=data["linhas_por_tabela"]
        if (not isinstance(counts,dict) or set(counts)!=set(_TABLES[store])
                or any(type(v) is not int or v<0 for v in counts.values())):
            raise ErroBackupConab("contagens do manifesto inválidas")
        try:
            ini=datetime.fromisoformat(data["capturado_inicio_utc"])
            fim=datetime.fromisoformat(data["capturado_fim_utc"])
            if (ini.tzinfo is None or fim.tzinfo is None or ini>fim):
                raise ValueError("instantes incoerentes")
        except (TypeError,ValueError) as exc:
            raise ErroBackupConab("janela de snapshot inválida") from exc
    return v


def _caracterizar_par(legado: sqlite3.Connection, canonico: sqlite3.Connection):
    try:
        _verificar_esquemas(legado, canonico)
    except ValueError as exc:
        raise ErroBackupConab("schema esperado CONAB não encontrado") from exc
    return {
        "LEGADO":_verificar_integridade(legado,"LEGADO"),
        "CANONICO":_verificar_integridade(canonico,"CANONICO"),
    }


def criar_backup_conab(legado_path: str | Path,
                       canonico_path: str | Path,
                       destino_dir: str | Path) -> dict:
    """Copia online cada banco isoladamente e confere a cópia.

    Se um banco sofrer escrita enquanto o outro é capturado, as duas cópias
    podem representar instantes lógicos distintos. Esse risco permanece
    explicitamente declarado, nunca tratado como consistência cross-DB.
    """
    origens = {"LEGADO":_path_file(legado_path),"CANONICO":_path_file(canonico_path)}
    if origens["LEGADO"].samefile(origens["CANONICO"]):
        raise ErroBackupConab("origens precisam ser bancos distintos")
    target = _diretorio_privado_vazio(destino_dir)
    opened,created = {},[]
    try:
        for store,path in origens.items():
            opened[store] = _readonly(path)
        _caracterizar_par(opened["LEGADO"], opened["CANONICO"])
        meta = {}
        for store,src in opened.items():
            path=target/_FILES[store]
            _new_private_file(path)
            created.append(path)
            begin=datetime.now(timezone.utc).isoformat()
            with sqlite3.connect(str(path),timeout=10) as backup_db:
                src.backup(backup_db, pages=64, sleep=0.05)
            end=datetime.now(timezone.utc).isoformat()
            with closing(_readonly(path)) as validated:
                counts = _verificar_integridade(validated,store)
            meta[store] = {
                "arquivo":_FILES[store],"sha256":_sha(path),
                "bytes":path.stat().st_size,
                "linhas_por_tabela":counts,"capturado_inicio_utc":begin,
                "capturado_fim_utc":end,"integridade_sqlite":"ok",
            }
        with closing(_readonly(target/_FILES["LEGADO"])) as a, \
             closing(_readonly(target/_FILES["CANONICO"])) as b:
            _caracterizar_par(a,b)
        manifest={
            "schema":_SCHEMA,"criado_utc":datetime.now(timezone.utc).isoformat(),
            "arquivos":meta,"consistencia_entre_bancos":"NAO_ATOMICA",
            "contem_raw_externo":False,"direitos_validos_comprovados":False,
            "apto_migracao_producao":False,
        }
        _json_exclusivo(target/_MANIFEST,manifest)
        created.append(target/_MANIFEST)
        return {
            "estado":"BACKUP_SQLITE_LOCAL_VERIFICADO_NAO_ATOMICO_ENTRE_BANCOS",
            "arquivos":2,"manifesto_gerado":True,
            "restauracao_testada":False,
            "migracao_permitida":False,
        }
    except (OSError,sqlite3.Error,ValueError):
        for p in reversed(created):
            p.unlink(missing_ok=True)
        raise
    finally:
        for db in opened.values():
            db.close()


def restaurar_em_diretorio_novo(backup_dir: str | Path,
                               destino_dir: str | Path) -> dict:
    """Restaura apenas em diretório previamente vazio e privado.

    Nunca grava nos bancos originais; checa SHA dos snapshots ANTES e
    DEPOIS, integrity_check e FK, em ambos os arquivos restaurados.
    """
    backup = Path(backup_dir)
    if not backup.is_absolute() or backup.is_symlink() or not backup.is_dir():
        raise ErroBackupConab("diretório do backup inválido")
    target = _diretorio_privado_vazio(destino_dir)
    if backup.resolve() == target.resolve():
        raise ErroBackupConab("backup e restauração devem usar diretórios distintos")
    manifest=_ler_manifesto(backup/_MANIFEST)
    files={}
    for store,name in _FILES.items():
        src=_path_file(backup/name)
        info=manifest["arquivos"][store]
        if src.stat().st_size!=info["bytes"] or _sha(src)!=info["sha256"]:
            raise ErroBackupConab("hash/tamanho do backup mudou; abortar restauração")
        files[store]=src
    created=[]
    try:
        for store,src in files.items():
            dst=target/_FILES[store]
            with src.open("rb") as r, dst.open("xb") as w:
                created.append(dst)
                if os.name=="posix":
                    dst.chmod(0o600)
                shutil.copyfileobj(r,w,1024*1024)
                w.flush()
                os.fsync(w.fileno())
            if dst.stat().st_size!=manifest["arquivos"][store]["bytes"] or \
               _sha(dst)!=manifest["arquivos"][store]["sha256"]:
                raise ErroBackupConab("cópia restaurada não preserva SHA")
        with closing(_readonly(target/_FILES["LEGADO"])) as a, \
             closing(_readonly(target/_FILES["CANONICO"])) as b:
            counts=_caracterizar_par(a,b)
        for store in _FILES:
            if counts[store]!=manifest["arquivos"][store]["linhas_por_tabela"]:
                raise ErroBackupConab("restauração não reproduz contagens do backup")
        report={
            "schema":"NIVON_CONAB_RESTORE_CHECK_V1",
            "verificado_utc":datetime.now(timezone.utc).isoformat(),
            "hashes_iguais":True,"integridade_sqlite":"ok",
            "foreign_keys_integras":True,"contagens_iguais":True,
            "restaurado_sem_sobrescrever":True,
            "consistencia_entre_bancos":"NAO_ATOMICA",
            "migracao_ou_publicacao_liberada":False,
        }
        _json_exclusivo(target/_RESTORE,report)
        created.append(target/_RESTORE)
        return report
    except (OSError,sqlite3.Error,ValueError):
        for p in reversed(created):
            p.unlink(missing_ok=True)
        raise


def main(argv=None) -> int:
    parser=argparse.ArgumentParser(description="NIVON CONAB: backup/restauração local e privado, sem migração")
    sub=parser.add_subparsers(dest="acao",required=True)
    b=sub.add_parser("backup")
    b.add_argument("--legado",required=True)
    b.add_argument("--canonico",required=True)
    b.add_argument("--destino",required=True)
    r=sub.add_parser("restaurar")
    r.add_argument("--backup",required=True)
    r.add_argument("--destino",required=True)
    args=parser.parse_args(argv)
    try:
        if args.acao=="backup":
            result=criar_backup_conab(args.legado,args.canonico,args.destino)
        else:
            result=restaurar_em_diretorio_novo(args.backup,args.destino)
    except (OSError,sqlite3.Error,ValueError) as exc:
        parser.error(str(exc))
    print(json.dumps(result,ensure_ascii=False,sort_keys=True,indent=2))
    return 0


if __name__=="__main__":
    raise SystemExit(main())
