"""Verificação estrita do RECORD de um wheel, sem extração nem instalação.

Escopo deliberadamente restrito do padrão wheel: SHA-256 em todos os arquivos
exceto RECORD, cuja linha possui hash/tamanho vazios. Assinaturas RECORD.jws
e RECORD.p7s depreciadas exigem auditoria manual e são recusadas.
"""
from __future__ import annotations

import base64
import binascii
import csv
import hashlib
import io
import re
import zipfile

from .auditoria_evidencias_pacotes import ErroEvidencia

MAX_RECORD_BYTES = 2_000_000
MAX_RECORD_ROWS = 10_000
_DIGEST = re.compile(r"sha256=([A-Za-z0-9_-]{43})\Z")
_SIZE = re.compile(r"0|[1-9][0-9]*\Z")


def verificar_record(zf: zipfile.ZipFile, members: dict, dist_dir: str) -> dict:
    """Compara cada arquivo do ZIP com a linha e o digest de RECORD.

    Recebe diretório .dist-info verificado externamente e entradas ZipInfo
    validadas (limites de quantidade, tamanho, expansão, symlinks e paths).
    """
    record_path = dist_dir + "/RECORD"
    if record_path not in members:
        raise ErroEvidencia("wheel sem RECORD obrigatório")
    info = members[record_path]
    if info.file_size > MAX_RECORD_BYTES:
        raise ErroEvidencia("RECORD grande demais")
    try:
        with zf.open(info) as stream:
            raw = stream.read(MAX_RECORD_BYTES + 1)
        if len(raw) > MAX_RECORD_BYTES:
            raise ErroEvidencia("RECORD excedeu tamanho máximo")
        text = raw.decode("utf-8", errors="strict")
        linhas = list(csv.reader(io.StringIO(text, newline=""), strict=True))
    except (UnicodeError, csv.Error, ValueError, RuntimeError,
            EOFError, OSError, zipfile.BadZipFile) as exc:
        raise ErroEvidencia("RECORD ilegível ou CSV inválido") from exc
    if not linhas or len(linhas) > MAX_RECORD_ROWS:
        raise ErroEvidencia("RECORD vazio ou com excesso de linhas")

    expected = {name for name in members if not name.endswith("/")}
    # As antigas assinaturas não são verificadas por esta implementação.
    if any(name.endswith(("/RECORD.jws", "/RECORD.p7s")) for name in expected):
        raise ErroEvidencia("assinatura RECORD legada exige revisão independente")

    entries = {}
    for row in linhas:
        if len(row) != 3:
            raise ErroEvidencia("RECORD exige exatamente path, hash e tamanho")
        name, digest, raw_size = row
        if (not name or "\\" in name or name.startswith("/") or
                "//" in name or any(seg in ("", ".", "..") for seg in name.split("/"))):
            raise ErroEvidencia("RECORD contém caminho inválido")
        if name in entries:
            raise ErroEvidencia("RECORD contém entrada duplicada")
        entries[name] = (digest, raw_size)

    if set(entries) != expected:
        raise ErroEvidencia("RECORD não cobre exatamente todos os arquivos do wheel")

    count = 0
    for name, (digest, raw_size) in entries.items():
        if name == record_path:
            if digest or raw_size:
                raise ErroEvidencia("RECORD não pode declarar hash ou tamanho próprio")
            continue
        match = _DIGEST.fullmatch(digest)
        if not match:
            raise ErroEvidencia("RECORD exige sha256 válido em cada arquivo")
        try:
            decoded = base64.urlsafe_b64decode(match.group(1) + "=")
        except (ValueError, binascii.Error) as exc:
            raise ErroEvidencia("RECORD contém base64 inválido") from exc
        if len(decoded) != 32 or base64.urlsafe_b64encode(decoded).decode("ascii").rstrip("=") != match.group(1):
            raise ErroEvidencia("RECORD contém digest sha256 não canônico")
        if not _SIZE.fullmatch(raw_size):
            raise ErroEvidencia("RECORD exige tamanho decimal em cada arquivo")
        item = members[name]
        if int(raw_size) != item.file_size:
            raise ErroEvidencia("tamanho de arquivo diverge do RECORD: " + name)
        digest_check = hashlib.sha256()
        bytes_read = 0
        try:
            with zf.open(item) as stream:
                while chunk := stream.read(1024 * 1024):
                    bytes_read += len(chunk)
                    if bytes_read > item.file_size:
                        raise ErroEvidencia("arquivo ZIP excede tamanho declarado")
                    digest_check.update(chunk)
        except (RuntimeError, EOFError, OSError, zipfile.BadZipFile, NotImplementedError) as exc:
            raise ErroEvidencia("arquivo ZIP corrompido durante RECORD") from exc
        if bytes_read != item.file_size or digest_check.digest() != decoded:
            raise ErroEvidencia("digest de arquivo diverge do RECORD: " + name)
        count += 1
    return {"record_integrity_verified": True, "record_hashed_files": count}
