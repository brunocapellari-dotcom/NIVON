"""Inventário direto de dependências do NIVON; nunca instala ou consulta rede.

Este é um gate de HIGIENE das declarações do pyproject, não scanner CVE,
SBOM transitive, certificado de licença nem aprovação de release.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import tomllib
from collections import defaultdict
from pathlib import Path

from .auditoria_extras import ErroDependencias, analisar_requisito, chave_requisito

ROOT = Path(__file__).resolve().parents[2]
_NOME = re.compile(r"[A-Za-z][A-Za-z0-9_.-]*\Z")
_TAMANHO_MAX = 80_000


class ErroDependencia(ValueError):
    """Declaração fora do subconjunto auditável ou insegura."""


def _nome(nome: str) -> str:
    if not isinstance(nome, str) or not _NOME.fullmatch(nome):
        raise ErroDependencia("nome de distribuição ou extra inválido")
    return re.sub(r"[-_.]+", "-", nome).casefold()


def _requisito(declaracao: str) -> tuple[str, str, tuple]:
    """Usa parser único da auditoria IVO; aplica gate mais rigoroso do inventário.

    Este inventário requer pin exato ou exatamente uma faixa inferior e superior
    ESTRITAMENTE ordenada. O parser compartilhado também aceita o requisito
    livre de build, que é tratado separadamente e nunca permite deploy.
    """
    if not isinstance(declaracao, str) or len(declaracao) > 180:
        raise ErroDependencia("dependência inválida ou extensa")
    try:
        parsed = analisar_requisito(declaracao)
    except ErroDependencias as exc:
        raise ErroDependencia("dependência fora do subconjunto seguro") from exc
    nome = parsed["distribution"]
    if not re.fullmatch(r"[a-z][a-z0-9-]*", nome):
        raise ErroDependencia("nome de distribuição inválido")
    chave = chave_requisito(parsed)
    if parsed["exact_pin"]:
        return nome, "==" + parsed["constraints"][0][1], chave
    # A comparação usa a mesma chave semântica que o pré-voo IVO.
    # Faixas estritas têm um operador inferior e um superior distintos.
    versoes_canonicas = {op: versao for op, versao in chave}
    bounds = [(op, val, versoes_canonicas[op]) for op, val in parsed["constraints"]]
    lows = [(op, val, canonical) for op, val, canonical in bounds if op in (">", ">=")]
    ups = [(op, val, canonical) for op, val, canonical in bounds if op in ("<", "<=")]
    if len(parsed["constraints"]) != 2 or len(lows) != 1 or len(ups) != 1:
        raise ErroDependencia(f"{nome}: faixa de versão não permitida")
    lo, hi = lows[0], ups[0]
    if lo[2] >= hi[2]:
        raise ErroDependencia(f"{nome}: intervalo vazio/invertido")
    return nome, lo[0] + lo[1] + "," + hi[0] + hi[1], chave


def inventariar(pyproject: str) -> dict:
    if not isinstance(pyproject, str) or len(pyproject.encode("utf-8")) > _TAMANHO_MAX:
        raise ErroDependencia("pyproject inválido ou grande")
    try:
        doc = tomllib.loads(pyproject)
        project = doc["project"]
        build = doc["build-system"]
    except (tomllib.TOMLDecodeError, KeyError, TypeError) as exc:
        raise ErroDependencia("TOML inválido ou seções ausentes") from exc
    if not isinstance(project, dict) or project.get("name") != "nivon":
        raise ErroDependencia("projeto não é NIVON")
    if project.get("requires-python") != ">=3.11":
        raise ErroDependencia("runtime Python diferente do auditado")
    if not isinstance(build, dict):
        raise ErroDependencia("build-system inválido")
    raw_build = build.get("requires")
    if not isinstance(raw_build, list) or not raw_build:
        raise ErroDependencia("dependências de build ausentes")
    if any(not isinstance(d, str) or not d.strip() for d in raw_build):
        raise ErroDependencia("dependência de build inválida")

    core = project.get("dependencies", [])
    extras = project.get("optional-dependencies", {})
    if not isinstance(core, list) or not isinstance(extras, dict):
        raise ErroDependencia("listas de dependências inválidas")

    vistos: dict[str, str] = {}
    chaves: dict[str, tuple] = {}
    grupos: dict[str, set[str]] = defaultdict(set)
    def registrar(items: list, origem: str) -> None:
        if not isinstance(items, list):
            raise ErroDependencia(f"grupo não é lista: {origem}")
        nomes_no_grupo: set[str] = set()
        for item in items:
            nome, constraint, chave = _requisito(item)
            if nome in nomes_no_grupo:
                raise ErroDependencia(f"distribuição duplicada no grupo {origem}: {nome}")
            nomes_no_grupo.add(nome)
            if nome in chaves and chaves[nome] != chave:
                raise ErroDependencia(f"distribuição com faixas divergentes: {nome}")
            vistos.setdefault(nome, constraint)
            chaves[nome] = chave
            grupos[nome].add(origem)

    registrar(core, "core")
    extras_vistos: set[str] = set()
    for extra, items in extras.items():
        norm = _nome(extra)
        if norm in extras_vistos or norm == "core":
            raise ErroDependencia("extras duplicados por normalização")
        extras_vistos.add(norm)
        registrar(items, norm)

    # Build requirements são inspecionadas separadamente porque o setup pré-instala
    # ferramentas antes do runtime. Nada é instalado por este gate.
    build_revisao = []
    for item in raw_build:
        try:
            name, constraint, _ = _requisito(item)
            risco = None
        except ErroDependencia:
            # Build permite >= como risco explícito, mas não URL, marker, VCS
            # nem faixa parcialmente oculta. A sintaxe vem do mesmo parser.
            try:
                parsed = analisar_requisito(item)
            except ErroDependencias as exc:
                raise ErroDependencia("requisito de build não auditável") from exc
            clauses = parsed["constraints"]
            if len(clauses) != 1 or clauses[0][0] != ">=":
                raise ErroDependencia("requisito de build não auditável")
            name, constraint = parsed["distribution"], ">=" + clauses[0][1]
            risco = "BUILD_REQUIRES_MANUAL_RESOLUTION_REVIEW"
        build_revisao.append({"distribution": name, "declared": constraint, "risk": risco})

    deps = [{"distribution": nome, "constraints": vistos[nome],
             "groups": sorted(grupos[nome]), "installed": False,
             "transitive_review": "PENDING", "cve_review": "PENDING",
             "license_review": "PENDING", "hash_lock": "MISSING"}
            for nome in sorted(vistos)]
    return {
        "project": "NIVON",
        "policy": "DIRECT_DECLARATIONS_ONLY_NO_INSTALL_NO_CVE_ATTESTATION",
        "pyproject_sha256": hashlib.sha256(pyproject.encode("utf-8")).hexdigest(),
        "runtime_python": project["requires-python"],
        "default_runtime_dependency_count": len(core),
        "optional_extras": sorted(extras_vistos),
        "direct_distribution_count": len(deps),
        "build_requirements": build_revisao,
        "dependencies": deps,
        "transitive_sbom_generated": False,
        "installed_packages_verified": False,
        "known_vulnerabilities_checked": False,
        "approved_for_install": False,
        "approved_for_production": False,
    }


def auditar(raiz: Path = ROOT) -> dict:
    path = raiz / "pyproject.toml"
    if path.is_symlink() or not path.is_file() or path.stat().st_size > _TAMANHO_MAX:
        raise ErroDependencia("pyproject ausente, link ou extenso")
    return inventariar(path.read_text(encoding="utf-8"))


def main() -> int:
    parser = argparse.ArgumentParser(description="Verificar declarações de dependências NIVON offline")
    parser.add_argument("--verificar", action="store_true")
    parser.add_argument("--root", type=Path, default=ROOT)
    args = parser.parse_args()
    try:
        report = auditar(args.root)
    except (ErroDependencia, UnicodeError) as exc:
        parser.exit(2, f"DEPENDENCIAS_BLOQUEADAS: {exc}\n")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
