"""Backup e restauração SQLite com verificação de integridade.

Funciona localmente para bancos NIVON sem precisar de provedor ou credencial.
Não é backup em nuvem: cópias devem ser levadas a armazenamento durável.
"""
from __future__ import annotations

import hashlib
import os
import sqlite3
import tempfile
from pathlib import Path
from urllib.parse import quote


class ErroBackup(ValueError):
    pass


def _sha256_stream(caminho: Path) -> str:
    """Hash em blocos de 256 KiB; não carregar SQLite inteiro em memória."""
    digest = hashlib.sha256()
    with caminho.open("rb") as arquivo:
        for bloco in iter(lambda: arquivo.read(262144), b""):
            digest.update(bloco)
    return digest.hexdigest()


def _integridade(db: sqlite3.Connection) -> None:
    status = db.execute("PRAGMA integrity_check").fetchone()
    if not status or status[0] != "ok":
        raise ErroBackup("PRAGMA integrity_check falhou")
    if db.execute("PRAGMA foreign_key_check").fetchone():
        raise ErroBackup("chaves estrangeiras inconsistentes")


def _snapshot_para(conn: sqlite3.Connection, destino: Path) -> str:
    if destino.exists() or destino.is_symlink():
        raise ErroBackup("destino existente; backup nunca sobrescreve")
    parent = destino.parent
    if not parent.is_dir():
        raise ErroBackup("diretório de destino ausente")
    fd, nome_temp = tempfile.mkstemp(prefix=".nivon-backup-", suffix=".sqlite", dir=parent)
    os.fchmod(fd, 0o600)
    os.close(fd)
    temporario = Path(nome_temp)
    try:
        with sqlite3.connect(str(temporario)) as backup:
            conn.backup(backup)
            _integridade(backup)
        with temporario.open("rb") as arquivo:
            if arquivo.read(16) != b"SQLite format 3\x00":
                raise ErroBackup("assinatura SQLite inválida")
        hash_arquivo = _sha256_stream(temporario)
        with temporario.open("rb") as arquivo:
            os.fsync(arquivo.fileno())
        # Link atômico: impede substituir um backup concorrente já existente.
        try:
            os.link(str(temporario), str(destino))
        except FileExistsError as exc:
            raise ErroBackup("backup de mesmo nome criado concorrentemente") from exc
        return hash_arquivo
    finally:
        temporario.unlink(missing_ok=True)


def criar_backup(conn: sqlite3.Connection, destino: str | Path) -> dict:
    """Cópia coerente, mesmo se o banco estiver em WAL; arquivo com permissão 0600."""
    _integridade(conn)
    path = Path(destino)
    hash_arquivo = _snapshot_para(conn, path)
    return {"destino": str(path), "sha256": hash_arquivo,
            "bytes": path.stat().st_size, "integridade": "OK",
            "natureza": "BACKUP_SQLITE_LOCAL_NAO_NUVEM"}


def restaurar_backup(origem: str | Path, destino: str | Path, *,
                     sha256_esperado: str | None = None) -> dict:
    """Restaura em NOVO caminho, sem sobrescrever bancos existentes.

    Verifica SHA-256 fornecido, PRAGMA integrity_check e foreign_key_check.
    """
    origem = Path(origem)
    destino = Path(destino)
    if origem.is_symlink() or not origem.is_file():
        raise ErroBackup("backup de origem precisa ser arquivo regular sem link simbólico")
    if not 0 < origem.stat().st_size <= 1_000_000_000:
        raise ErroBackup("backup vazio ou acima do limite de 1 GB")
    hash_atual = _sha256_stream(origem)
    if sha256_esperado is not None and hash_atual != sha256_esperado:
        raise ErroBackup("SHA-256 divergente")
    url = "file:" + quote(str(origem.absolute()), safe="/") + "?mode=ro"
    try:
        with sqlite3.connect(url, uri=True) as leitor:
            _integridade(leitor)
            hash_restaurado = _snapshot_para(leitor, destino)
    except sqlite3.DatabaseError as exc:
        raise ErroBackup("backup SQLite ilegível ou corrompido") from exc
    return {"destino": str(destino), "sha256": hash_restaurado,
            "integridade": "OK",
            "natureza": "RESTAURADO_LOCALMENTE_SEM_SOBRESCRITA"}
