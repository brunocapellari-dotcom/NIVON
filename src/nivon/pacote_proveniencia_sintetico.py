"""Pacote ZIP sintético para ensaiar a emissão de atestação no GitHub Actions.

NÃO resolve pacotes, NÃO executa pip/pip-audit, NÃO consulta rede e NUNCA
habilita instalação ou produção. Prova somente que o workflow consegue
produzir bytes reprodutíveis do contrato e um SHA256 local conferível.
"""
from __future__ import annotations

import argparse
import hashlib
import io
import json
import os
import re
import stat
import zipfile
from pathlib import Path

from .auditoria_evidencias_pacotes import ErroEvidencia

MAX_INPUT = 80_000
MAX_ZIP = 160_000
REPO = "brunocapellari-dotcom/NIVON"
_SHA = re.compile(r"[0-9a-f]{40}\Z")
_FILES = ("manifesto.json", "pyproject.toml")
SCHEMA = "NIVON_SYNTHETIC_PROVENANCE_PILOT_V1"


def _regular_bytes(path: Path, limit: int) -> bytes:
    if path.is_symlink():
        raise ErroEvidencia("fonte sintética é symlink")
    flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0)
    try:
        fd = os.open(path, flags)
        with os.fdopen(fd, "rb") as f:
            meta = os.fstat(f.fileno())
            if not stat.S_ISREG(meta.st_mode) or meta.st_size > limit:
                raise ErroEvidencia("fonte sintética não é arquivo regular permitido")
            data = f.read(limit + 1)
            if len(data) > limit or len(data) != meta.st_size:
                raise ErroEvidencia("fonte sintética excedeu limite ou mudou")
            return data
    except OSError as exc:
        raise ErroEvidencia("falha ao ler fonte sintética") from exc


def _identidade(repo: str, sha: str, run_id: int) -> None:
    if (repo != REPO or not isinstance(sha, str) or not _SHA.fullmatch(sha)
            or type(run_id) is not int or run_id < 1):
        raise ErroEvidencia("identificadores sintéticos inválidos")


def _zipinfo(path: str) -> zipfile.ZipInfo:
    info = zipfile.ZipInfo(path, date_time=(1980, 1, 1, 0, 0, 0))
    info.compress_type = zipfile.ZIP_STORED
    info.create_system = 3
    info.external_attr = (stat.S_IFREG | 0o644) << 16
    return info


def criar_pacote(pyproject: bytes, *, repo: str, source_sha: str, run_id: int) -> bytes:
    _identidade(repo, source_sha, run_id)
    if not isinstance(pyproject, bytes) or not pyproject or len(pyproject) > MAX_INPUT:
        raise ErroEvidencia("pyproject sintético ausente ou excessivo")
    # Apenas texto do repositório público, sem rede, secrets ou metadados pessoais.
    try:
        pyproject.decode("utf-8", errors="strict")
    except UnicodeError as exc:
        raise ErroEvidencia("pyproject não é UTF-8") from exc
    manifest = {
        "schema": SCHEMA,
        "evidence_type": "SYNTHETIC_WORKFLOW_TEST_NOT_DEPENDENCY_EVIDENCE",
        "repository": repo,
        "source_sha": source_sha,
        "workflow_run_id": run_id,
        "files": {
            "pyproject.toml": {
                "sha256": hashlib.sha256(pyproject).hexdigest(),
                "bytes": len(pyproject),
            },
        },
        "third_party_downloads_performed": False,
        "pip_install_performed": False,
        "dependency_resolution_performed": False,
        "real_vulnerability_scan_performed": False,
        "third_party_license_review_performed": False,
        "approved_for_install": False,
        "approved_for_production": False,
        "release_gate": "BLOCKED_SYNTHETIC_WORKFLOW_PILOT_ONLY",
    }
    manifest_bytes = (json.dumps(manifest, sort_keys=True, ensure_ascii=False,
                                 separators=(",", ":")) + "\n").encode("utf-8")
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr(_zipinfo("manifesto.json"), manifest_bytes)
        archive.writestr(_zipinfo("pyproject.toml"), pyproject)
    result = buffer.getvalue()
    if len(result) > MAX_ZIP:
        raise ErroEvidencia("ZIP sintético excessivo")
    verificar_pacote(result, repo=repo, source_sha=source_sha, run_id=run_id)
    return result


def _unique_json(payload: bytes) -> dict:
    def pairs(items):
        o = {}
        for k, v in items:
            if k in o:
                raise ErroEvidencia("JSON sintético duplicado")
            o[k] = v
        return o
    try:
        parsed = json.loads(payload.decode("utf-8"), object_pairs_hook=pairs)
    except (UnicodeError, ValueError) as exc:
        raise ErroEvidencia("manifesto sintético inválido") from exc
    if not isinstance(parsed, dict):
        raise ErroEvidencia("manifesto sintético precisa ser objeto")
    return parsed


def verificar_pacote(payload: bytes, *, repo: str, source_sha: str, run_id: int) -> dict:
    """Confere apenas o conteúdo do ensaio; não verifica assinatura Sigstore."""
    _identidade(repo, source_sha, run_id)
    if not isinstance(payload, bytes) or len(payload) > MAX_ZIP:
        raise ErroEvidencia("ZIP sintético inválido ou excessivo")
    try:
        with zipfile.ZipFile(io.BytesIO(payload), "r") as archive:
            names = archive.namelist()
            if names != list(_FILES):
                raise ErroEvidencia("ZIP sintético com arquivos faltantes/extras")
            if any(archive.getinfo(n).file_size > MAX_INPUT for n in names):
                raise ErroEvidencia("arquivo interno grande demais")
            manifest = _unique_json(archive.read("manifesto.json"))
            project = archive.read("pyproject.toml")
    except (zipfile.BadZipFile, zipfile.LargeZipFile, OSError, RuntimeError) as exc:
        raise ErroEvidencia("ZIP sintético corrompido") from exc
    if (manifest.get("schema") != SCHEMA or
            manifest.get("evidence_type") != "SYNTHETIC_WORKFLOW_TEST_NOT_DEPENDENCY_EVIDENCE" or
            manifest.get("repository") != repo or
            manifest.get("source_sha") != source_sha or
            type(manifest.get("workflow_run_id")) is not int or
            manifest["workflow_run_id"] != run_id or
            manifest.get("files") != {
                "pyproject.toml": {
                    "sha256": hashlib.sha256(project).hexdigest(),
                    "bytes": len(project),
                },
            }):
        raise ErroEvidencia("manifesto não coincide com bytes do ZIP")
    for key in ("third_party_downloads_performed", "pip_install_performed",
                "dependency_resolution_performed", "real_vulnerability_scan_performed",
                "third_party_license_review_performed", "approved_for_install",
                "approved_for_production"):
        if manifest.get(key) is not False:
            raise ErroEvidencia("manifesto sintético apresenta falsa aprovação/execução")
    if manifest.get("release_gate") != "BLOCKED_SYNTHETIC_WORKFLOW_PILOT_ONLY":
        raise ErroEvidencia("gate de liberação sintética adulterado")
    return {
        "schema": SCHEMA,
        "zip_sha256": hashlib.sha256(payload).hexdigest(),
        "zip_bytes": len(payload),
        "source_sha": source_sha,
        "workflow_run_id": run_id,
        "synthetic_content_consistent": True,
        "github_signature_verified": False,
        "external_packages_verified": False,
        "approved_for_production": False,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Ensaio sintético de proveniência, sem pip e sem rede")
    parser.add_argument("--pyproject", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--repository", required=True)
    parser.add_argument("--source-sha", required=True)
    parser.add_argument("--run-id", type=int, required=True)
    args = parser.parse_args()
    try:
        raw = _regular_bytes(args.pyproject, MAX_INPUT)
        output = criar_pacote(raw, repo=args.repository, source_sha=args.source_sha,
                              run_id=args.run_id)
        if args.output.is_symlink() or args.output.exists():
            raise ErroEvidencia("arquivo de saída existente/symlink; não sobrescrever")
        if not args.output.parent.is_dir() or args.output.parent.is_symlink():
            raise ErroEvidencia("diretório de saída ausente ou symlink")
        flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0)
        fd = os.open(args.output, flags, 0o600)
        with os.fdopen(fd, "wb") as f:
            f.write(output)
        result = verificar_pacote(_regular_bytes(args.output, MAX_ZIP),
                                 repo=args.repository, source_sha=args.source_sha,
                                 run_id=args.run_id)
    except (ErroEvidencia, OSError) as exc:
        parser.exit(2, f"PACOTE_SINTETICO_BLOQUEADO: {exc}\n")
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
