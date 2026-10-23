"""Inventário offline de metadados de licença de um wheel, segundo PEP 639.

Confere integridade e localização das declarações e dos arquivos listados.
Não valida sintaxe SPDX integral, direitos autorais, compatibilidade de
licenças, autenticidade do fornecedor ou autorização de uso/distribuição.
"""
from __future__ import annotations

import hashlib
import re
import zipfile
from email.message import Message

from .auditoria_evidencias_pacotes import ErroEvidencia

MAX_LICENSE_FILES = 32
MAX_LICENSE_FILE_BYTES = 1024 * 1024
MAX_LICENSE_TOTAL_BYTES = 4 * 1024 * 1024
MAX_LICENSE_PATH = 256
MAX_LICENSE_EXPRESSION = 512
_VERSION = re.compile(r"[0-9]+\.[0-9]+\Z")
_SAFE_SEGMENT = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.+() -]*\Z")


def _validar_caminho(caminho: str) -> str:
    if (not isinstance(caminho, str) or not caminho or
            len(caminho) > MAX_LICENSE_PATH or caminho.startswith("/") or
            "\\" in caminho or ":" in caminho or "\x00" in caminho or
            "\n" in caminho or "\r" in caminho):
        raise ErroEvidencia("License-File com caminho inválido")
    segmentos = caminho.split("/")
    if any(seg in ("", ".", "..") or not _SAFE_SEGMENT.fullmatch(seg)
           for seg in segmentos):
        raise ErroEvidencia("License-File com caminho inseguro")
    return caminho


def inspecionar_licenca(zf: zipfile.ZipFile, members: dict,
                       dist_dir: str, metadata: Message) -> dict:
    """Inventaria declarações do archive já validado e nunca aprova licença.

    O chamador deve ter conferido SHA256 do wheel e seu RECORD; os digests
    calculados aqui representam evidência local, não assinatura do titular.
    """
    versoes = metadata.get_all("Metadata-Version", [])
    if len(versoes) != 1 or not _VERSION.fullmatch(str(versoes[0])):
        raise ErroEvidencia("Metadata-Version ausente, duplicado ou inválido")
    versao = tuple(int(x) for x in str(versoes[0]).split("."))
    express = metadata.get_all("License-Expression", [])
    legacy = metadata.get_all("License", [])
    declared = metadata.get_all("License-File", [])
    if len(express) > 1 or len(legacy) > 1 or len(declared) > MAX_LICENSE_FILES:
        raise ErroEvidencia("campos de licença duplicados ou excessivos")
    if express:
        expression = str(express[0])
        if (versao < (2, 4) or not expression.strip() or
                len(expression) > MAX_LICENSE_EXPRESSION or
                any(ord(c) < 32 or ord(c) > 126 for c in expression)):
            raise ErroEvidencia("License-Expression inválida para versão de METADATA")
    else:
        expression = None
    if versao >= (2, 4) and expression and legacy:
        raise ErroEvidencia("License e License-Expression mutuamente exclusivas")
    if versao >= (2, 4) and declared and legacy and expression:
        raise ErroEvidencia("metadados contraditórios de licença")

    files = []
    vistos = set()
    total = 0
    for raw in declared:
        caminho = _validar_caminho(str(raw))
        if caminho in vistos:
            raise ErroEvidencia("License-File duplicado")
        vistos.add(caminho)
        if versao < (2, 4):
            # Wheels antigos podem usar caminhos e convenções distintos.
            # Preservar a declaração, sem alegar verificação da localização.
            files.append({"declared_path": caminho,
                          "verified_path": None, "sha256": None,
                          "path_checked": False, "utf8_checked": False})
            continue
        interno = dist_dir + "/licenses/" + caminho
        if interno not in members or interno.endswith("/"):
            raise ErroEvidencia("License-File declarada não existe no wheel: " + caminho)
        info = members[interno]
        if info.file_size > MAX_LICENSE_FILE_BYTES:
            raise ErroEvidencia("arquivo de licença grande demais")
        total += info.file_size
        if total > MAX_LICENSE_TOTAL_BYTES:
            raise ErroEvidencia("arquivos de licença grandes demais")
        try:
            with zf.open(info) as stream:
                content = stream.read(MAX_LICENSE_FILE_BYTES + 1)
            if len(content) != info.file_size or len(content) > MAX_LICENSE_FILE_BYTES:
                raise ErroEvidencia("arquivo de licença incompleto ou excessivo")
            content.decode("utf-8", errors="strict")
        except UnicodeError as exc:
            raise ErroEvidencia("arquivo de licença não é UTF-8") from exc
        except (OSError, RuntimeError, EOFError, zipfile.BadZipFile) as exc:
            raise ErroEvidencia("arquivo de licença corrompido") from exc
        files.append({
            "declared_path": caminho,
            "verified_path": interno,
            "sha256": hashlib.sha256(content).hexdigest(),
            "bytes": len(content),
            "path_checked": True,
            "utf8_checked": True,
        })

    if versao < (2, 4):
        status = "LEGACY_METADATA_MANUAL_REVIEW"
    elif expression:
        status = "SPDX_EXPRESSION_DECLARED_UNVERIFIED"
    else:
        status = "SPDX_EXPRESSION_ABSENT_MANUAL_REVIEW"
    return {
        "metadata_version": str(versoes[0]),
        "license_expression_declared": expression,
        "legacy_license_field_present": bool(legacy),
        "license_file_count": len(files),
        "license_files": files,
        "license_metadata_status": status,
        "license_files_presence_utf8_checked": versao >= (2, 4),
        "spdx_expression_parsed_or_validated": False,
        "license_content_legally_reviewed": False,
        "licenses_approved": False,
        "source_provenance_authenticated": False,
    }
