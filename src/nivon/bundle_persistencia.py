"""Snapshots consistentes por banco, manifesto e recuperação do estado NIVON.

Escopo: progresso CONAB, programações portuárias e outbox do briefing.
Não afirma consistência transacional ENTRE bancos nem cloud durável. O chamador
deve pausar escritores ANTES da captura, em um diretório privado já preparado.
Nenhuma API de nuvem, cron, deploy ou coleta é iniciada automaticamente.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import sqlite3
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from contextlib import closing
from typing import Mapping

from .backup_sqlite import criar_backup, restaurar_backup, ErroBackup

_DB_NAMES = ("conab", "portos", "outbox")
_BATCH_RE = re.compile(r"[a-zA-Z0-9][a-zA-Z0-9_-]{3,79}\Z")
_SHA_RE = re.compile(r"[a-f0-9]{64}\Z")


class ErroBundle(ValueError):
    pass


def _dir_seguro(p: Path) -> None:
    if p.is_symlink() or not p.is_dir() or (p.stat().st_mode & 0o077):
        raise ErroBundle("diretório de armazenamento precisa existir, sem symlink, modo 0700")
    if not p.is_absolute():
        raise ErroBundle("caminho absoluto obrigatório")


def _id_valido(ident: str) -> None:
    if not isinstance(ident, str) or not _BATCH_RE.fullmatch(ident):
        raise ErroBundle("identificador de snapshot inválido")


def _json_restrito(path: Path) -> dict:
    if path.is_symlink() or not path.is_file() or path.stat().st_size > 32_768:
        raise ErroBundle("manifesto inexistente, symlink ou acima do limite")
    with path.open("rb") as f:
        dados = json.load(f)
    if not isinstance(dados, dict):
        raise ErroBundle("manifesto não é objeto JSON")
    return dados


def _fsync_dir(path: Path) -> None:
    fd = os.open(path, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def salvar_ponto_recuperacao(*, bancos: Mapping[str, sqlite3.Connection],
                           destino_raiz: str | Path, snapshot_id: str,
                           escritores_pausados: bool = False,
                           coletado_em: str) -> dict:
    """Não pode ser chamado se houver escritores concorrentes nos bancos.

    Basta uma falha para descartar o diretório de snapshot incompleto.
    A marca COMPLETO é escrita e sincronizada somente após os três backups.
    """
    if escritores_pausados is not True:
        raise PermissionError("ponto de recuperação exige janela sem escritores")
    _id_valido(snapshot_id)
    if not isinstance(bancos, Mapping) or set(bancos) != set(_DB_NAMES):
        raise ErroBundle("os três bancos são obrigatórios")
    try:
        instante = datetime.fromisoformat(coletado_em.replace("Z", "+00:00"))
    except (AttributeError, ValueError) as exc:
        raise ErroBundle("coletado_em inválido") from exc
    if instante.tzinfo is None or instante.utcoffset() is None:
        raise ErroBundle("instante do backup sem fuso")
    root = Path(destino_raiz)
    _dir_seguro(root)
    final = root / snapshot_id
    # Criação privada exclusiva. Nunca sobrescreve evidência já registrada.
    try:
        final.mkdir(mode=0o700, exist_ok=False)
    except FileExistsError as exc:
        raise ErroBundle("snapshot id já existe") from exc
    try:
        backups = {}
        for nome in _DB_NAMES:
            info = criar_backup(bancos[nome], final / (nome + ".sqlite"))
            backups[nome] = {
                "filename": nome + ".sqlite",
                "sha256": info["sha256"],
                "bytes": info["bytes"],
                "integridade": info["integridade"],
            }
        manifest = {
            "schema": "NIVON_SQLITE_BUNDLE_V1",
            "snapshot_id": snapshot_id,
            "coletado_em": instante.astimezone(timezone.utc).isoformat(),
            "backup_por_banco_coerente": True,
            "consistencia_entre_bancos_nao_garantida": True,
            "armazenamento_nuvem_comprovado": False,
            "bancos": backups,
            "status": "COMPLETO_LOCAL_SEM_PROVA_NUVEM",
        }
        data = json.dumps(manifest, ensure_ascii=False, sort_keys=True,
                          separators=(",",":"), allow_nan=False).encode("utf-8")
        fd = os.open(final / "manifest.json",
                     os.O_CREAT | os.O_EXCL | os.O_WRONLY | getattr(os,"O_NOFOLLOW",0),
                     0o600)
        with os.fdopen(fd,"wb") as f:
            f.write(data)
            f.flush()
            os.fsync(f.fileno())
        _fsync_dir(final)
        _fsync_dir(root)
        return {"status": manifest["status"],"snapshot_id":snapshot_id,
                "manifest_sha256": hashlib.sha256(data).hexdigest(),
                "bancos": tuple(backups),
                "diretorio": str(final),
                "cloud_duravel": False}
    except BaseException:
        # A função criou final com exclusividade e somente os 4 arquivos esperados.
        for nome in tuple(x + ".sqlite" for x in _DB_NAMES) + ("manifest.json",):
            (final / nome).unlink(missing_ok=True)
        final.rmdir()
        raise


def verificar_ponto_recuperacao(*, raiz: str | Path,
                              snapshot_id: str) -> dict:
    """Verifica metadados, hash e integridade SQLite sem restaurar dados."""
    _id_valido(snapshot_id)
    root=Path(raiz)
    _dir_seguro(root)
    pasta=root / snapshot_id
    _dir_seguro(pasta)
    manifest=_json_restrito(pasta / "manifest.json")
    if (manifest.get("schema") != "NIVON_SQLITE_BUNDLE_V1"
        or manifest.get("snapshot_id") != snapshot_id
        or manifest.get("status") != "COMPLETO_LOCAL_SEM_PROVA_NUVEM"
        or not isinstance(manifest.get("bancos"), dict)
        or set(manifest["bancos"]) != set(_DB_NAMES)):
        raise ErroBundle("manifesto não reconhecido ou incompleto")
    status={}
    for nome in _DB_NAMES:
        info=manifest["bancos"][nome]
        if not isinstance(info, dict) or info.get("filename") != nome+".sqlite":
            raise ErroBundle("arquivo de banco fora da lista autorizada")
        digest=info.get("sha256")
        if not isinstance(digest,str) or not _SHA_RE.fullmatch(digest):
            raise ErroBundle("SHA do manifesto inválido")
        arquivo=pasta / info["filename"]
        if arquivo.is_symlink() or not arquivo.is_file() or arquivo.stat().st_size!=info.get("bytes"):
            raise ErroBundle("arquivo ausente ou tamanho divergente")
        h=hashlib.sha256()
        with arquivo.open("rb") as f:
            for bloco in iter(lambda:f.read(262144),b""):
                h.update(bloco)
        if h.hexdigest()!=digest:
            raise ErroBundle("SHA do banco divergente")
        # Abrir somente leitura, inclusive quando WAL original existia.
        from urllib.parse import quote
        uri="file:"+quote(str(arquivo.absolute()),safe="/")+"?mode=ro"
        try:
            with closing(sqlite3.connect(uri,uri=True,timeout=5)) as db:
                r=db.execute("PRAGMA integrity_check").fetchone()
                fk=db.execute("PRAGMA foreign_key_check").fetchone()
                if r is None or r[0]!="ok" or fk is not None:
                    raise ErroBundle("SQLite inconsistente")
        except sqlite3.DatabaseError as exc:
            raise ErroBundle("SQLite ilegível") from exc
        status[nome]="VERIFICADO"
    return {"snapshot_id":snapshot_id,"status":"VERIFICADO_LOCAL",
            "bancos":status,"armazenamento_nuvem_comprovado":False,
            "manifest":manifest}


def recuperar_ponto(*, raiz: str | Path, snapshot_id: str,
                   destino_novo: str | Path) -> dict:
    """Restaura três bancos em NOVO diretório vazio, sem sobrescrita."""
    v=verificar_ponto_recuperacao(raiz=raiz,snapshot_id=snapshot_id)
    dest=Path(destino_novo)
    if dest.exists() or dest.is_symlink():
        raise ErroBundle("recuperação não sobrescreve diretório existente")
    if not dest.is_absolute():
        raise ErroBundle("destino deve ser absoluto")
    _dir_seguro(dest.parent)
    dest.mkdir(mode=0o700,exist_ok=False)
    try:
        for nome in _DB_NAMES:
            info=v["manifest"]["bancos"][nome]
            restaurar_backup(Path(raiz)/snapshot_id/info["filename"],
                             dest/(nome+".sqlite"),
                             sha256_esperado=info["sha256"])
        _fsync_dir(dest)
        return {"status":"RESTAURADO_EM_DIRETORIO_NOVO",
                "bancos":_DB_NAMES,
                "diretorio":str(dest),
                "requires_manual_cutover":True}
    except BaseException:
        for nome in _DB_NAMES:
            (dest/(nome+".sqlite")).unlink(missing_ok=True)
        dest.rmdir()
        raise
