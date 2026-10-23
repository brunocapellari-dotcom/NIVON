"""Gate local de dependências declaradas em wheels, sem resolver nem instalar.

Somente interpreta o subconjunto numérico e incondicional de Requires-Dist
que a auditoria NIVON já suporta. Markers, extras, referências remotas e
sintaxe PEP 508 não suportada bloqueiam o gate — não são ignorados.
"""
from __future__ import annotations

import argparse
import json
import re
import tomllib
from pathlib import Path

from .auditoria_evidencias_pacotes import (
    ErroEvidencia, _arquivo, _dentro_do_requisito, _lock,
)
from .auditoria_extras import ErroDependencias, analisar_requisito
from .auditoria_wheelhouse import verificar

_PARENTHESES = re.compile(r"^\s*([A-Za-z0-9][A-Za-z0-9_.-]*)\s*\(\s*([^()]*)\s*\)\s*$")
MAX_REQUIREMENTS = 20000


def _parse_require(texto: str) -> dict:
    if not isinstance(texto, str) or len(texto) > 512:
        raise ErroEvidencia("Requires-Dist vazio, extenso ou inválido")
    m = _PARENTHESES.fullmatch(texto)
    if m:
        texto = m.group(1) + m.group(2).strip()
    try:
        return analisar_requisito(texto)
    except ErroDependencias as exc:
        raise ErroEvidencia("Requires-Dist fora do contrato auditável: " + texto[:80]) from exc


def analisar_fechamento(pyproject: str, lock_text: str, rodas: dict,
                       extras_escolhidos: list[str]) -> dict:
    """Prova apenas coerência das arestas incondicionais declaradas.

    O inventário de rodas deve provir do validador de RECORD/wheelhouse. Como
    dados passados podem ser forjados, esta função isolada não autentica hash.
    """
    if not isinstance(pyproject, str) or len(pyproject.encode("utf-8")) > 80_000:
        raise ErroEvidencia("pyproject inválido ou extenso")
    try:
        project = tomllib.loads(pyproject)["project"]
        if project.get("name") != "nivon":
            raise ErroEvidencia("projeto diferente do NIVON")
        extras = project["optional-dependencies"]
        core = project.get("dependencies", [])
    except (tomllib.TOMLDecodeError, KeyError, TypeError, AttributeError) as exc:
        raise ErroEvidencia("pyproject inválido para grafo") from exc
    if not isinstance(core, list) or not isinstance(extras, dict):
        raise ErroEvidencia("grupos pyproject inválidos")
    if (not isinstance(extras_escolhidos, list) or not extras_escolhidos or
            any(not isinstance(x, str) or x not in extras for x in extras_escolhidos) or
            len(set(extras_escolhidos)) != len(extras_escolhidos)):
        raise ErroEvidencia("extra selecionado ausente ou duplicado")
    if not isinstance(rodas, dict) or rodas.get("wheel_record_integrity_verified") is not True:
        raise ErroEvidencia("wheelhouse não atesta RECORD íntegro")
    entries = rodas.get("verified_wheels")
    if not isinstance(entries, list):
        raise ErroEvidencia("wheelhouse sem lista de distribuições")

    locked = _lock(lock_text)
    by_name = {}
    for item in entries:
        if not isinstance(item, dict):
            raise ErroEvidencia("wheel de estrutura inválida")
        name, version = item.get("distribution"), item.get("version")
        if (not isinstance(name, str) or not isinstance(version, str) or
                name in by_name or name not in locked or
                locked[name]["version"] != version or
                item.get("record_integrity_verified") is not True or
                not isinstance(item.get("requires_dist"), list)):
            raise ErroEvidencia("wheel inválido ou sem dependências auditáveis")
        by_name[name] = item
    if set(by_name) != set(locked):
        raise ErroEvidencia("wheelhouse incompleto para fechamento")

    obligations = []
    for req in core:
        obligations.append(("pyproject:core", req))
    for extra in extras_escolhidos:
        if not isinstance(extras[extra], list):
            raise ErroEvidencia("extra não é lista")
        for req in extras[extra]:
            obligations.append(("pyproject:" + extra, req))
    for name, item in sorted(by_name.items()):
        if len(item["requires_dist"]) > 512:
            raise ErroEvidencia("wheel com dependências excessivas")
        for req in item["requires_dist"]:
            obligations.append((name, req))
    if len(obligations) > MAX_REQUIREMENTS:
        raise ErroEvidencia("grafo de dependências grande demais")

    edges = []
    for origin, raw in obligations:
        parsed = _parse_require(raw)
        dep = parsed["distribution"]
        if dep not in locked:
            raise ErroEvidencia(f"dependência ausente do lock: {origin} -> {dep}")
        if not _dentro_do_requisito(locked[dep]["version"], parsed):
            raise ErroEvidencia(f"dependência com versão incompatível: {origin} -> {dep}")
        edges.append({"source": origin, "requires": dep, "requirement": raw,
                      "locked_version": locked[dep]["version"]})
    return {
        "project": "NIVON",
        "analysis_type": "OFFLINE_SUPPORTED_UNCONDITIONAL_REQUIRES_DIST_ONLY",
        "selected_extras": sorted(extras_escolhidos),
        "locked_package_count": len(locked),
        "declared_edges_checked": len(edges),
        "edges": edges,
        "unconditional_supported_requirements_consistent": True,
        "all_pep508_requirements_supported": False,
        "resolver_transitive_closure_attested": False,
        "environment_markers_evaluated": False,
        "wheel_platform_compatibility_checked": False,
        "licenses_reviewed": False,
        "vulnerabilities_scanned": False,
        "packages_installed": False,
        "approved_for_install": False,
        "approved_for_production": False,
        "release_gate": "BLOCKED_PENDING_FULL_PEP508_LOCK_PROVENANCE_CVE_LICENSE_RUNTIME",
    }


def auditar(wheelhouse: Path, pyproject: str, lock_text: str, extras: list[str]) -> dict:
    wheels = verificar(wheelhouse, lock_text)
    return analisar_fechamento(pyproject, lock_text, wheels, extras)


def main() -> int:
    parser = argparse.ArgumentParser(description="Grafo de dependências declaradas, offline")
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[2])
    parser.add_argument("--wheelhouse", type=Path, required=True)
    parser.add_argument("--lock", type=Path, required=True)
    parser.add_argument("--extra", action="append", required=True)
    args = parser.parse_args()
    try:
        resultado = auditar(args.wheelhouse,
                            _arquivo(args.root / "pyproject.toml", 80_000),
                            _arquivo(args.lock, 300_000), args.extra)
    except (ErroEvidencia, OSError) as exc:
        parser.exit(2, f"FECHAMENTO_BLOQUEADO: {exc}\n")
    print(json.dumps(resultado, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
