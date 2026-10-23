"""Backup/restore OFFLINE, fechado por padrão, da outbox SQLite NIVON.

Não envia nem restaura em produção; funções só agem em paths explicitamente
fornecidos e recusam overwrite. Verifica integridade e checksum lógico,
incluindo consentimentos, reservas, ACK, recibos e quarentena.
"""
from __future__ import annotations

import hashlib
import json
import os
import sqlite3
from pathlib import Path


class ErroBackup(ValueError):
    pass


def _path(path: str | Path, *, precisa_existir: bool) -> Path:
    p=Path(path)
    if not p.is_absolute() or p.is_symlink() or not p.parent.is_dir():
        raise ErroBackup("arquivo de backup requer caminho absoluto e parent existente")
    if precisa_existir and (not p.is_file() or p.is_symlink()):
        raise ErroBackup("backup ausente ou inseguro")
    if not precisa_existir and p.exists():
        raise FileExistsError("destino já existe; sobrescrita proibida")
    return p


def _novo_exclusivo(path: Path) -> None:
    flags=os.O_WRONLY | os.O_CREAT | os.O_EXCL
    if hasattr(os,"O_NOFOLLOW"):
        flags|=os.O_NOFOLLOW
    fd=os.open(path,flags,0o600)
    os.close(fd)


def _ident(nome: str) -> str:
    return '"'+nome.replace('"','""')+'"'


def _valor(x):
    if isinstance(x,bytes):
        return {"hex":x.hex()}
    return x


def estado_logico(db: sqlite3.Connection) -> dict:
    """Resumo sem valores sensíveis; checksum estável mesmo após restore."""
    if db.execute("PRAGMA integrity_check").fetchone()[0]!="ok":
        raise ErroBackup("integridade SQLite reprovada")
    fk=list(db.execute("PRAGMA foreign_key_check"))
    if fk:
        raise ErroBackup("foreign key órfã no backup")
    # O digest anterior só cobria linhas: um schema adulterado de tabela
    # vazia poderia passar. Atar também DDL, views, índices e triggers.
    schema=[tuple(row) for row in db.execute("""SELECT type,name,tbl_name,sql
        FROM sqlite_master WHERE sql IS NOT NULL AND name NOT LIKE 'sqlite_stat%'
        ORDER BY type,name,tbl_name""")]
    schema_blob=json.dumps(schema,ensure_ascii=False,sort_keys=True,
                           separators=(",",":")).encode("utf-8")
    esquema_sha256=hashlib.sha256(schema_blob).hexdigest()
    nomes=sorted(row[0] for row in db.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND "
        "(name NOT LIKE 'sqlite_%' OR name='sqlite_sequence')"))
    sha=hashlib.sha256()
    sha.update(b"NIVON:OUTBOX:LOGICAL_BACKUP:V2\\n")
    sha.update(esquema_sha256.encode("ascii"))
    counts={}
    for nome in nomes:
        colunas=db.execute(f"PRAGMA table_info({_ident(nome)})").fetchall()
        if not colunas:
            raise ErroBackup("esquema sem colunas")
        order=",".join(str(i) for i in range(1,len(colunas)+1))
        n=0
        for row in db.execute(f"SELECT * FROM {_ident(nome)} ORDER BY {order}"):
            serial=json.dumps([_valor(x) for x in row],ensure_ascii=False,
                              sort_keys=True,allow_nan=False,
                              separators=(",",":")).encode("utf-8")
            sha.update(len(serial).to_bytes(8,"big"))
            sha.update(serial)
            n+=1
        counts[nome]=n
        sha.update(json.dumps({"tabela":nome,"linhas":n},
                              sort_keys=True).encode("utf-8"))
    return {"tabelas":counts,"total_linhas":sum(counts.values()),
            "esquema_sha256":esquema_sha256,
            "conteudo_sha256":sha.hexdigest(),"integridade":"OK"}


def _file_sha(path: Path) -> str:
    sha=hashlib.sha256()
    with open(path,"rb") as f:
        for chunk in iter(lambda:f.read(1024*1024),b""):
            sha.update(chunk)
    return sha.hexdigest()


def _ro_db(path: Path) -> sqlite3.Connection:
    # Caminho local existente, nunca URL HTTP/rede.
    con=sqlite3.connect(path.as_uri()+"?mode=ro",uri=True,timeout=15)
    con.execute("PRAGMA query_only=ON")
    return con


def verificar_backup(path: str | Path, *, sha256_esperado: str | None = None) -> dict:
    p=_path(path,precisa_existir=True)
    if p.stat().st_size>4_000_000_000:
        raise ErroBackup("backup excede limite da rotina piloto")
    with open(p,"rb") as f:
        if f.read(16)!=b"SQLite format 3\x00":
            raise ErroBackup("arquivo não é SQLite")
    checksum=_file_sha(p)
    if sha256_esperado is not None and checksum!=sha256_esperado:
        raise ErroBackup("checksum de arquivo não confere")
    con=_ro_db(p)
    try:
        logical=estado_logico(con)
    finally:
        con.close()
    return {**logical,"arquivo_sha256":checksum,"somente_leitura":True}


def criar_backup_validado(
    origem: sqlite3.Connection, *, destino: str | Path,
    autorizar_backup: bool = False,
) -> dict:
    if autorizar_backup is not True:
        raise PermissionError("backup não habilitado")
    if origem.in_transaction:
        raise ErroBackup("backup requer conexão em estado transacional limpo")
    path=_path(destino,precisa_existir=False)
    source=estado_logico(origem)
    _novo_exclusivo(path)
    try:
        copy=sqlite3.connect(path)
        try:
            origem.backup(copy)
        finally:
            copy.close()
        verificado=verificar_backup(path)
        if source["conteudo_sha256"]!=verificado["conteudo_sha256"]:
            raise ErroBackup("backup divergente de origem; possível escrita simultânea")
        return {**verificado,"estado":"BACKUP_VALIDADO_LOCAL",
                "copia_remota":False,"publicacao_autorizada":False}
    except Exception:
        path.unlink(missing_ok=True)
        raise


def restaurar_backup_validado(
    backup: str | Path, *, destino: str | Path,
    sha256_esperado: str,
    autorizar_restauracao: bool = False,
) -> dict:
    if autorizar_restauracao is not True:
        raise PermissionError("restore não autorizado")
    manifest=verificar_backup(backup,sha256_esperado=sha256_esperado)
    target=_path(destino,precisa_existir=False)
    _novo_exclusivo(target)
    try:
        original=_ro_db(_path(backup,precisa_existir=True))
        try:
            restored=sqlite3.connect(target)
            try:
                original.backup(restored)
            finally:
                restored.close()
        finally:
            original.close()
        state=verificar_backup(target)
        if state["conteudo_sha256"]!=manifest["conteudo_sha256"]:
            raise ErroBackup("restauração perdeu/alterou registros")
        return {**state,"estado":"RESTORE_VALIDADO_LOCAL",
                "backup_origem_sha256":manifest["arquivo_sha256"],
                "envio_executado":False}
    except Exception:
        target.unlink(missing_ok=True)
        raise
