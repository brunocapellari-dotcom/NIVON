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

ROOT = Path(__file__).resolve().parents[2]
_NOME = re.compile(r"[A-Za-z][A-Za-z0-9_.-]*\Z")
_ESPEC = re.compile(r"(==|>=|>|<=|<)\s*(\d+(?:\.\d+){0,3})\Z")
_VERSAO = re.compile(r"\d+(?:\.\d+){0,3}\Z")
_TAMANHO_MAX = 80_000


class ErroDependencia(ValueError):
    """Declaração fora do subconjunto auditável ou insegura."""


def _nome(nome: str) -> str:
    if not isinstance(nome, str) or not _NOME.fullmatch(nome):
        raise ErroDependencia("nome de distribuição ou extra inválido")
    return re.sub(r"[-_.]+", "-", nome).casefold()


def _versao(texto: str) -> tuple[int, ...]:
    if not _VERSAO.fullmatch(texto):
        raise ErroDependencia("versão não numérica")
    return tuple(int(x) for x in texto.split("."))


def _comparar(a: tuple[int, ...], b: tuple[int, ...]) -> int:
    a = a + (0,) * (4 - len(a))
    b = b + (0,) * (4 - len(b))
    return (a > b) - (a < b)


def _requisito(declaracao: str) -> tuple[str, str]:
    """Somente versões diretas explícitas: pin exato ou faixa inferior/superior.

    Recusa URLs diretas, markers, extras transitivos e operadores sem gate.
    A sintaxe deliberadamente é mais restrita que PEP 508.
    """
    if not isinstance(declaracao, str) or len(declaracao) > 180:
        raise ErroDependencia("dependência inválida ou extensa")
    if any(x in declaracao for x in ("@", ";", "://", "[", "]", "\\", "/")):
        raise ErroDependencia("referência direta, marker ou extra aninhado não auditado")
    m = re.fullmatch(r"\s*([A-Za-z][A-Za-z0-9_.-]*)\s*(.*?)\s*", declaracao)
    if m is None or not m.group(2).strip():
        raise ErroDependencia("versão obrigatória para dependência")
    nome = _nome(m.group(1))
    partes = [x.strip() for x in m.group(2).split(",")]
    if len(partes) not in (1, 2) or any(not x for x in partes):
        raise ErroDependencia(f"{nome}: faixa de versão não permitida")
    parsed = []
    for parte in partes:
        p = _ESPEC.fullmatch(parte)
        if not p:
            raise ErroDependencia(f"{nome}: especificador de versão não suportado")
        parsed.append((p.group(1), _versao(p.group(2)), p.group(2)))
    if len(parsed) == 1:
        if parsed[0][0] != "==":
            raise ErroDependencia(f"{nome}: versão flutuante sem limite superior/inferior")
        return nome, "==" + parsed[0][2]
    lows = [(op, val, raw) for op, val, raw in parsed if op in (">", ">=")]
    ups = [(op, val, raw) for op, val, raw in parsed if op in ("<", "<=")]
    if len(lows) != 1 or len(ups) != 1:
        raise ErroDependencia(f"{nome}: intervalo deve ter exatamente dois limites")
    lower, upper = lows[0], ups[0]
    if _comparar(lower[1], upper[1]) >= 0:
        raise ErroDependencia(f"{nome}: intervalo vazio/invertido")
    return nome, lower[0] + lower[2] + "," + upper[0] + upper[2]


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
    grupos: dict[str, set[str]] = defaultdict(set)
    def registrar(items: list, origem: str) -> None:
        if not isinstance(items, list):
            raise ErroDependencia(f"grupo não é lista: {origem}")
        nomes_no_grupo: set[str] = set()
        for item in items:
            nome, constraint = _requisito(item)
            if nome in nomes_no_grupo:
                raise ErroDependencia(f"distribuição duplicada no grupo {origem}: {nome}")
            nomes_no_grupo.add(nome)
            if nome in vistos and vistos[nome] != constraint:
                raise ErroDependencia(f"distribuição com faixas divergentes: {nome}")
            vistos[nome] = constraint
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
            name, constraint = _requisito(item)
            risco = None
        except ErroDependencia:
            m = re.match(r"\s*([A-Za-z][A-Za-z0-9_.-]*)", item)
            if not m:
                raise ErroDependencia("nome da ferramenta de build inválido")
            name, constraint = _nome(m.group(1)), item
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
