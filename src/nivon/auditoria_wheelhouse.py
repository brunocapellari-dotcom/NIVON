"""Verifica arquivos wheel reais contra hashes DECLARADOS em lock, sem instalar.

Inspeciona somente ZIP e metadados locais sob limites. Não executa código,
não baixa dependências, não valida assinatura/origem, licença ou ABI,
compatibilidade com plataforma nem fechamento transitivo (PEP 508).
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import stat
import zipfile
from email import policy
from email.parser import BytesParser
from pathlib import Path

from .auditoria_evidencias_pacotes import ErroEvidencia, _arquivo, _lock
from .auditoria_extras import ErroDependencias, analisar_requisito
from .verificacao_record import verificar_record

MAX_WHEEL_BYTES = 128 * 1024 * 1024
MAX_ENTRIES = 10000
MAX_EXPANDED_BYTES = 512 * 1024 * 1024
MAX_METADATA_BYTES = 256 * 1024
MAX_EXPANSION_RATIO = 2000
MAX_PACKAGE_COUNT = 2000
_WHEEL_TAG = re.compile(r"[A-Za-z0-9_.]+\Z")
_WHEEL_VERSION = re.compile(r"\d+(?:\.\d+){0,3}\Z")


def _package(nome: str, versao: str) -> str:
    try:
        return analisar_requisito(nome + "==" + versao)["distribution"]
    except ErroDependencias as exc:
        raise ErroEvidencia("identidade wheel inválida") from exc


def _filename(file_name: str) -> tuple[str, str]:
    if not isinstance(file_name, str) or not file_name.endswith(".whl"):
        raise ErroEvidencia("arquivo não é wheel")
    partes = file_name[:-4].split("-")
    if len(partes) not in (5, 6):
        raise ErroEvidencia("nome wheel fora do formato aceito")
    nome, versao, *tags = partes
    if not nome or not _WHEEL_VERSION.fullmatch(versao):
        raise ErroEvidencia("versão/nome wheel incompatível")
    if not all(_WHEEL_TAG.fullmatch(tag) for tag in tags):
        raise ErroEvidencia("tag wheel inválida")
    return _package(nome, versao), versao


def _metadata_zip(fh, expected_name: str, expected_version: str) -> dict:
    try:
        with zipfile.ZipFile(fh, mode="r") as zf:
            infos = zf.infolist()
            if not infos or len(infos) > MAX_ENTRIES:
                raise ErroEvidencia("wheel vazio ou excesso de membros")
            members = {}
            total_expanded = 0
            for item in infos:
                path = item.filename
                if (not path or "\\" in path or path.startswith("/") or
                        "//" in path or any(part in (".", "..") for part in path.split("/"))):
                    raise ErroEvidencia("membro ZIP com caminho inseguro")
                if path in members:
                    raise ErroEvidencia("membro ZIP duplicado")
                members[path] = item
                mode = item.external_attr >> 16
                if stat.S_IFMT(mode) == stat.S_IFLNK:
                    raise ErroEvidencia("wheel contém symlink")
                if item.flag_bits & 1:
                    raise ErroEvidencia("wheel contém membro criptografado")
                if item.file_size < 0 or item.compress_size < 0:
                    raise ErroEvidencia("tamanho ZIP inválido")
                total_expanded += item.file_size
                if total_expanded > MAX_EXPANDED_BYTES:
                    raise ErroEvidencia("wheel excede limite total expandido")
                if item.file_size > MAX_METADATA_BYTES and (
                        path.endswith(".dist-info/METADATA") or path.endswith(".dist-info/WHEEL")):
                    raise ErroEvidencia("metadados wheel grandes demais")
                if item.file_size > MAX_EXPANSION_RATIO * max(1, item.compress_size):
                    raise ErroEvidencia("taxa de expansão ZIP potencialmente perigosa")
            metas = [p for p in members if p.endswith(".dist-info/METADATA")]
            if len(metas) != 1:
                raise ErroEvidencia("wheel deve conter METADATA único")
            metadata_path = metas[0]
            dist_dir = metadata_path[:-len("/METADATA")]
            prefix = dist_dir[:-len(".dist-info")]
            if "-" not in prefix:
                raise ErroEvidencia("diretório dist-info inválido")
            dist, version = prefix.rsplit("-", 1)
            if _package(dist, version) != expected_name or version != expected_version:
                raise ErroEvidencia("dist-info difere de filename wheel")
            wheel_path = dist_dir + "/WHEEL"
            if wheel_path not in members:
                raise ErroEvidencia("cabeçalho WHEEL ausente")
            try:
                with zf.open(metadata_path) as stream:
                    payload = stream.read(MAX_METADATA_BYTES + 1)
                with zf.open(wheel_path) as stream:
                    wheel_header = stream.read(MAX_METADATA_BYTES + 1)
                if len(payload) > MAX_METADATA_BYTES or len(wheel_header) > MAX_METADATA_BYTES:
                    raise ErroEvidencia("metadados wheel excederam limite")
                meta = BytesParser(policy=policy.default).parsebytes(payload, headersonly=True)
                hdr = BytesParser(policy=policy.default).parsebytes(wheel_header, headersonly=True)
                name_header = meta.get_all("Name", [])
                version_header = meta.get_all("Version", [])
                wheel_versions = hdr.get_all("Wheel-Version", [])
                if len(name_header) != 1 or len(version_header) != 1 or len(wheel_versions) != 1:
                    raise ErroEvidencia("cabeçalhos obrigatórios ausentes/duplicados")
                if (_package(str(name_header[0]), str(version_header[0])) != expected_name or
                        str(version_header[0]) != expected_version):
                    raise ErroEvidencia("Name/Version em METADATA divergentes")
                if not str(wheel_versions[0]).startswith("1."):
                    raise ErroEvidencia("versão WHEEL incompatível")
                # Somente cabeçalhos de dependências; a interpretação do
                # grafo fica em auditoria_fechamento_pacotes, sem imports.
                req_headers = meta.get_all("Requires-Dist", [])
                if len(req_headers) > 512:
                    raise ErroEvidencia("METADATA contém excesso de dependências")
                requirements = [str(value) for value in req_headers]
                if any(not item.strip() or len(item) > 512 or
                       "\\n" in item or "\\r" in item for item in requirements):
                    raise ErroEvidencia("Requires-Dist inválido ou extenso")
            except ErroEvidencia:
                raise
            except (UnicodeError, ValueError, RuntimeError, EOFError,
                    NotImplementedError, zipfile.BadZipFile) as exc:
                raise ErroEvidencia("metadados wheel inválidos ou corrompidos") from exc
            record = verificar_record(zf, members, dist_dir)
            return {"zip_members": len(members), "dist_info_verified": True,
                    "requires_dist": requirements, **record}
    except (OSError, zipfile.BadZipFile, zipfile.LargeZipFile) as exc:
        raise ErroEvidencia("wheel ZIP ilegível/corrompido") from exc


def _verify_one(path: Path, expected_name: str, locked: dict) -> dict:
    fname_name, fname_version = _filename(path.name)
    if fname_name != expected_name or fname_version != locked["version"]:
        raise ErroEvidencia("identidade do arquivo diferente do lock")
    # O_NOFOLLOW protege a abertura mesmo diante de symlink trocado entre
    # listagem e uso. O mesmo FD é usado para hash e metadados.
    flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0)
    try:
        fd = os.open(path, flags)
        with os.fdopen(fd, "rb") as fh:
            actual = os.fstat(fh.fileno())
            if not stat.S_ISREG(actual.st_mode) or actual.st_size > MAX_WHEEL_BYTES:
                raise ErroEvidencia("arquivo wheel não regular ou grande demais")
            sha = hashlib.sha256()
            total = 0
            while True:
                chunk = fh.read(1 << 20)
                if not chunk:
                    break
                total += len(chunk)
                if total > MAX_WHEEL_BYTES:
                    raise ErroEvidencia("wheel excedeu tamanho permitido")
                sha.update(chunk)
            digest = sha.hexdigest()
            if digest not in locked["sha256_hashes"]:
                raise ErroEvidencia("SHA256 de wheel não confere com lock")
            fh.seek(0)
            detail = _metadata_zip(fh, expected_name, locked["version"])
            return {"distribution": expected_name, "version": locked["version"],
                    "wheel_file": path.name, "verified_sha256": digest,
                    "bytes": total, **detail}
    except OSError as exc:
        raise ErroEvidencia("erro de acesso seguro ao wheel") from exc


def verificar(wheelhouse: Path, lock_text: str) -> dict:
    """Hash de todos os arquivos wheel locais, sem resolver nem instalar."""
    root = Path(wheelhouse)
    if root.is_symlink() or not root.is_dir():
        raise ErroEvidencia("wheelhouse ausente, symlink ou não diretório")
    locked = _lock(lock_text)
    if len(locked) > MAX_PACKAGE_COUNT:
        raise ErroEvidencia("lock grande demais")
    results = {}
    with os.scandir(root) as scanner:
        files = list(scanner)
    if not files or len(files) > MAX_PACKAGE_COUNT:
        raise ErroEvidencia("wheelhouse vazio ou excessivo")
    for file in sorted(files, key=lambda x: x.name):
        if file.is_symlink() or not file.is_file(follow_symlinks=False):
            raise ErroEvidencia("wheelhouse contém symlink ou diretório")
        name, version = _filename(file.name)
        if name not in locked:
            raise ErroEvidencia("wheel extra não está no lock: " + name)
        if name in results:
            raise ErroEvidencia("mais de um wheel para mesma distribuição")
        if locked[name]["version"] != version:
            raise ErroEvidencia("versão wheel difere do lock: " + name)
        results[name] = _verify_one(Path(file.path), name, locked[name])
    if set(results) != set(locked):
        raise ErroEvidencia("wheelhouse não cobre todas as distribuições do lock")
    return {
        "project": "NIVON", "evidence_type": "LOCAL_WHEEL_BYTES_AND_METADATA",
        "wheel_count": len(results),
        "package_files_sha256_verified_against_declarations": True,
        "wheel_identity_headers_checked": True,
        "verified_wheels": [results[name] for name in sorted(results)],
        "wheel_record_integrity_verified": True,
        "wheel_tags_platform_compatible": False,
        "dependency_closure_verified": False,
        "provenance_authenticated": False,
        "vulnerabilities_scanned": False,
        "licenses_reviewed": False,
        "packages_installed": False,
        "approved_for_install": False,
        "approved_for_production": False,
        "release_gate": "BLOCKED_PENDING_AUTHENTICATED_ORIGIN_CLOSURE_CVE_LICENSE_AND_RUNTIME_TESTS",
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Validar wheelhouse por hashes offline, sem instalar")
    parser.add_argument("--wheelhouse", type=Path, required=True)
    parser.add_argument("--lock", type=Path, required=True)
    args = parser.parse_args()
    try:
        report = verificar(args.wheelhouse, _arquivo(args.lock, 300_000))
    except (ErroEvidencia, OSError) as exc:
        parser.exit(2, f"WHEELHOUSE_BLOQUEADA: {exc}\n")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
