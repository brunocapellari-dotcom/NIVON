"""Snapshot/validação da wheelhouse PyPI do NIVON, sem alterar o runtime.

Captura nomes e SHA-256 de arquivos públicos PyPI para AMD64/ARM64.
Verificação exige igualdade estrita, bloqueando resolução transitiva mutável.
"""
from __future__ import annotations
import argparse
import hashlib
import json
from pathlib import Path
import re

from .infra_supplychain import ErroSupplyChain

FILENAME = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.+-]{0,249}\.whl\Z")
SHA = re.compile(r"[0-9a-f]{64}\Z")
REQUIREMENTS = ("agrobr==2.0.0", "pandas>=2.2,<3", "statsforecast>=2,<3")
MAX_ENTRIES = 220
MAX_BYTES = 400_000_000
BASE = "python:3.11-slim-trixie@sha256:cce12316475d7d56d605f76e1d811d0dc4e7227f2d4afd29951521264f504ff8"


def coletar(folder: Path, arch: str) -> dict:
    if arch not in ("amd64", "arm64"):
        raise ErroSupplyChain("arquitetura do lock não homologada")
    if folder.is_symlink() or not folder.is_dir():
        raise ErroSupplyChain("wheelhouse não regular")
    items = sorted(folder.iterdir(), key=lambda p: p.name)
    if not 3 <= len(items) <= MAX_ENTRIES:
        raise ErroSupplyChain("quantidade de wheels inválida")
    result = []
    total = 0
    for path in items:
        if path.is_symlink() or not path.is_file() or not FILENAME.fullmatch(path.name):
            raise ErroSupplyChain("arquivo de wheelhouse não permitido")
        size = path.stat().st_size
        if not 0 < size <= MAX_BYTES or total + size > MAX_BYTES:
            raise ErroSupplyChain("tamanho de wheelhouse excedido")
        total += size
        digest = hashlib.sha256()
        with path.open("rb") as stream:
            for chunk in iter(lambda: stream.read(262144), b""):
                digest.update(chunk)
        result.append({"filename": path.name, "sha256": digest.hexdigest(), "bytes": size})
    return {
        "schema": "nivon.infra.analytics_wheel_lock.v1",
        "base_image": BASE, "arch": arch, "python_minor": "3.11",
        "wheel_only": True, "index": "https://pypi.org/simple",
        "requirements": list(REQUIREMENTS),
        "files": result,
        "total_bytes": total,
        "production_authorized": False,
        "security_audit_completed": False,
    }


def verificar(observed: dict, expected_file: Path) -> None:
    if expected_file.is_symlink() or not expected_file.is_file():
        raise ErroSupplyChain("lock versionado ausente")
    if expected_file.stat().st_size > 75_000:
        raise ErroSupplyChain("lock excessivo")
    try:
        with expected_file.open("r", encoding="utf-8") as stream:
            expected = json.load(stream)
    except (OSError, UnicodeError, ValueError) as exc:
        raise ErroSupplyChain("lock ilegível ou inválido") from exc
    if expected != observed:
        raise ErroSupplyChain("wheelhouse diverge do lock versionado")


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Inventário imutável de wheels PyPI")
    p.add_argument("--folder", required=True)
    p.add_argument("--arch", choices=("amd64", "arm64"), required=True)
    mode = p.add_mutually_exclusive_group(required=True)
    mode.add_argument("--emit", action="store_true")
    mode.add_argument("--check")
    a = p.parse_args(argv)
    try:
        got = coletar(Path(a.folder), a.arch)
        if a.check:
            verificar(got, Path(a.check))
    except (OSError, ValueError):
        print(json.dumps({"status": "WHEEL_LOCK_MISMATCH_OR_INVALID",
                          "production_authorized": False}, sort_keys=True))
        return 2
    if a.emit:
        print("NIVON_WHEEL_LOCK_CAPTURE=" + json.dumps(got, sort_keys=True, separators=(",", ":")))
    else:
        print(json.dumps({"status": "EXACT_WHEEL_LOCK_MATCH",
                          "wheel_count": len(got["files"]),
                          "arch": a.arch, "production_authorized": False}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
