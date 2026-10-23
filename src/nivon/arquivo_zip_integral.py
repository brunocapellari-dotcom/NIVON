"""Arquivo imutável do ZIP INMET pai, em fluxo, sem abrir rede.

Guarda a cópia integral por hash com verificação de membro CSV contra os bytes
normalizados. Cada ZIP é copiado uma única vez, mesmo quando possui N estações.
"""
from __future__ import annotations

from hashlib import sha256
import os
from pathlib import Path
import re
import tempfile

from .inmet_historico import obter_csv_em_memoria
from .pipeline_medicoes_horarias import ErroPipelineAmbiental, _pasta

_MAX_ZIP = 1_000_000_000
_HASH = re.compile(r"[0-9a-f]{64}\Z")


def _hash_file(path):
    h = sha256()
    with path.open("rb") as stream:
        while chunk := stream.read(1024*1024):
            h.update(chunk)
    return h.hexdigest()


def arquivar_zip_inmet(*, raw_dir, caminho_zip, hash_esperado):
    """Persiste ZIP fonte sob `raw_dir/origens/<sha>.zip`.

    Retenção do ZIP completo é requisito para ser elegível ao indicador de
    integridade técnica; fonte/autoridade e direitos de uso seguem pendentes.
    """
    if not isinstance(hash_esperado,str) or not _HASH.fullmatch(hash_esperado):
        raise ErroPipelineAmbiental("SHA do ZIP não canônico")
    original=Path(caminho_zip)
    if (original.is_symlink() or not original.is_file()
        or original.suffix.lower()!=".zip"
        or not 0<original.stat().st_size<=_MAX_ZIP):
        raise ErroPipelineAmbiental("ZIP de origem inseguro ou excessivo")
    raiz=_pasta(raw_dir,criar=True)
    pasta=_pasta(raiz/"origens",criar=True)
    target=pasta/(hash_esperado+".zip")
    if target.is_symlink():
        raise ErroPipelineAmbiental("container ZIP symlink no acervo")
    if target.exists():
        if not target.is_file() or _hash_file(target)!=hash_esperado:
            raise ErroPipelineAmbiental("ZIP original arquivado foi adulterado")
        return target
    fd,temp=tempfile.mkstemp(prefix=".inmetzip-",dir=pasta)
    try:
        os.fchmod(fd,0o600)
        with os.fdopen(fd,"wb") as output, original.open("rb") as source:
            digest=sha256()
            count=0
            while block:=source.read(1024*1024):
                count+=len(block)
                if count>_MAX_ZIP:
                    raise ErroPipelineAmbiental("ZIP excedeu limite na cópia")
                digest.update(block)
                output.write(block)
            output.flush()
            os.fsync(output.fileno())
        if digest.hexdigest()!=hash_esperado:
            raise ErroPipelineAmbiental("ZIP alterado entre pré-validação e arquivo")
        try:
            os.link(temp,target)
        except FileExistsError:
            if target.is_symlink() or _hash_file(target)!=hash_esperado:
                raise ErroPipelineAmbiental("colisão ou corrida no ZIP armazenado")
        return target
    finally:
        Path(temp).unlink(missing_ok=True)


def validar_zip_inmet_guardado(
    *, raw_dir, parent_sha256, membro_csv, membro_sha256, ano,
):
    """Reconstitui o membro CRC-validado a partir do ZIP **arquivado**."""
    if any(not isinstance(h,str) or not _HASH.fullmatch(h)
           for h in (parent_sha256,membro_sha256)):
        raise ErroPipelineAmbiental("hash ZIP/membro inválido")
    pasta=_pasta(Path(raw_dir)/"origens",criar=False)
    path=pasta/(parent_sha256+".zip")
    if path.is_symlink() or not path.is_file() or _hash_file(path)!=parent_sha256:
        raise ErroPipelineAmbiental("ZIP integral original ausente ou adulterado")
    raw=obter_csv_em_memoria(path,ano=ano,nome=membro_csv)
    if sha256(raw).hexdigest()!=membro_sha256:
        raise ErroPipelineAmbiental("CSV guardado difere do membro ZIP original")
    return {"zip_sha256":parent_sha256,"membro":membro_csv,
            "membro_sha256":membro_sha256,
            "zip_original_arquivado":True,"membro_conferido":True,
            "origem_http_autenticada":False}
