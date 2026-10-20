"""Pré-voo estático das dependências NIVON: fail-closed, sem instalar ou importar extras.

Esta inspeção verifica apenas declarações diretas do pyproject e seu vínculo ao
catálogo IVO. Não inspeciona dependências transitivas nem vulnerabilidades.
"""
from __future__ import annotations

import argparse
import json
import re
import tomllib
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
REPO_CONFIG = ROOT / "pyproject.toml"
IVO_CONFIG = ROOT / "config" / "ivo_ferramentas_github.v1.json"
PACOTES_IVO = {
    "STATSFORECAST": "statsforecast",
    "MLFORECAST": "mlforecast",
    "RIVER": "river",
    "DUCKDB": "duckdb",
}
NOME = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]*\Z")
CLAUSULA = re.compile(r"(==|>=|<=|>|<)\s*(\d+(?:\.\d+){0,3})\Z")


class ErroDependencias(ValueError):
    """Declaração incompatível com pré-voo seguro."""


def _normalizar(nome: str) -> str:
    if not isinstance(nome, str) or not NOME.fullmatch(nome):
        raise ErroDependencias("nome de distribuição inválido")
    return re.sub(r"[-_.]+", "-", nome).lower()


def analisar_requisito(texto: str) -> dict:
    """Aceita apenas um subconjunto explícito de versões PEP 440 usado no NIVON.

    URLs, VCS, paths, markers e extras aninhados exigem auditoria adicional e
    são recusados; nunca executar pip como efeito desta análise.
    """
    if not isinstance(texto, str):
        raise ErroDependencias("requisito não textual")
    match = re.fullmatch(r"\s*([A-Za-z0-9][A-Za-z0-9_.-]*)(.*)", texto)
    if match is None or not match.group(2).strip():
        raise ErroDependencias(f"requisito sem versão ou inválido: {texto!r}")
    pacote = _normalizar(match.group(1))
    clausulas = []
    for pedaco in match.group(2).split(","):
        parte = CLAUSULA.fullmatch(pedaco.strip())
        if parte is None:
            raise ErroDependencias(f"requisito não permitido ou fora do subconjunto auditado: {texto!r}")
        clausulas.append((parte.group(1), parte.group(2)))
    if len(set(clausulas)) != len(clausulas):
        raise ErroDependencias(f"restrição repetida: {pacote}")
    if any(op == "==" for op, _ in clausulas) and len(clausulas) != 1:
        raise ErroDependencias(f"pin exato misturado com outras faixas: {pacote}")
    lower = [(op, v) for op, v in clausulas if op in (">", ">=")]
    upper = [(op, v) for op, v in clausulas if op in ("<", "<=")]
    if lower and upper:
        # Normalização numérica: 2, 2.0 e 2.0.0 representam o mesmo limite.
        # Não substitui um resolver PEP 440 (pré-releases são recusados acima).
        def versao_chave(v: str) -> tuple[int, ...]:
            parts = tuple(int(n) for n in v.split("."))
            return parts + (0,) * (4 - len(parts))

        maxima_lower = max(versao_chave(v) for _, v in lower)
        minima_upper = min(versao_chave(v) for _, v in upper)
        if maxima_lower > minima_upper or (
            maxima_lower == minima_upper and
            (any(op == ">" for op, _ in lower) or any(op == "<" for op, _ in upper))
        ):
            raise ErroDependencias(f"faixa impossível: {pacote}")
    pin = len(clausulas) == 1 and clausulas[0][0] == "=="
    bounded = pin or bool(lower and upper)
    return {"distribution": pacote, "requirement": texto,
            "constraints": sorted(clausulas), "exact_pin": pin,
            "direct_range_bounded": bounded}


def _parse_lists(pyproject: dict) -> dict:
    try:
        build = pyproject["build-system"]["requires"]
        project = pyproject["project"]
        main = project.get("dependencies", [])
        extras = project.get("optional-dependencies", {})
    except (KeyError, TypeError, AttributeError) as exc:
        raise ErroDependencias("pyproject sem contratos de build/projeto") from exc
    if (not isinstance(project, dict) or not isinstance(build, list) or
            not isinstance(main, list) or not isinstance(extras, dict)):
        raise ErroDependencias("tipo de seção/lista de dependências inválido")
    for item in build + main:
        if not isinstance(item, str):
            raise ErroDependencias("dependência não textual")
    for value in extras.values():
        if not isinstance(value, list):
            raise ErroDependencias("extra exige lista")
    # Um único resultado de dependências sem resolver ou instalar pacotes.

    groups = {"build-system": build, "runtime": main}
    for key, deps in extras.items():
        if not isinstance(key, str) or not NOME.fullmatch(key) or not isinstance(deps, list):
            raise ErroDependencias("extra inválido")
        groups["extra:" + key] = deps
    return groups


def inspecionar(pyproject_texto: str, ivo: dict) -> dict:
    """Retorna inventário estático, nunca 'safe', SBOM ou instalação autorizada."""
    try:
        doc = tomllib.loads(pyproject_texto)
    except (TypeError, tomllib.TOMLDecodeError) as exc:
        raise ErroDependencias("TOML inválido") from exc
    groups = _parse_lists(doc)
    if not isinstance(ivo, dict) or not isinstance(ivo.get("components"), list):
        raise ErroDependencias("catálogo IVO ausente ou malformado")
    by_package: dict[str, list[tuple[str, dict]]] = defaultdict(list)
    for group, deps in sorted(groups.items()):
        seen = set()
        for req in deps:
            entry = analisar_requisito(req)
            name = entry["distribution"]
            if name in seen:
                raise ErroDependencias(f"duplicidade no grupo {group}: {name}")
            seen.add(name)
            by_package[name].append((group, entry))
    for package, entries in by_package.items():
        all_specs = {tuple(map(tuple, item["constraints"])) for _, item in entries}
        if len(all_specs) > 1:
            # Uma divergência em extras não é resolvida silenciosamente pelo pip.
            raise ErroDependencias(f"restrições diretas divergentes entre grupos: {package}")
    ids = {}
    for comp in ivo["components"]:
        if not isinstance(comp, dict) or not isinstance(comp.get("id"), str):
            raise ErroDependencias("registro IVO inválido")
        ids[comp["id"]] = comp
    for id_, package in PACOTES_IVO.items():
        if id_ not in ids or _normalizar(package) not in by_package:
            raise ErroDependencias(f"adaptador IVO sem dependência declarada: {id_}")
        if not any(group.startswith("extra:") for group, _ in by_package[package]):
            raise ErroDependencias(f"adaptador IVO não está em extra opt-in: {id_}")
        repo = ids[id_].get("repository")
        if not isinstance(repo, str) or not repo.startswith("https://github.com/"):
            raise ErroDependencias(f"proveniência de pacote IVO ausente: {id_}")
    packages = []
    for name, entries in sorted(by_package.items()):
        representative = entries[0][1]
        packages.append({"distribution": name, "groups": sorted(group for group, _ in entries),
                         "requirements": sorted({item["requirement"] for _, item in entries}),
                         "exact_pin": representative["exact_pin"],
                         "direct_range_bounded": representative["direct_range_bounded"]})
    not_exact = [x["distribution"] for x in packages if not x["exact_pin"]]
    unbounded = [x["distribution"] for x in packages if not x["direct_range_bounded"]]
    return {
        "project": "NIVON",
        "analysis_type": "STATIC_DIRECT_REQUIREMENTS_ONLY",
        "direct_packages": len(packages),
        "optional_extras": sorted(k[6:] for k in groups if k.startswith("extra:")),
        "ivo_optional_adapter_gates_checked": sorted(PACOTES_IVO),
        "not_exactly_pinned": not_exact,
        "direct_ranges_without_two_sided_bounds": unbounded,
        "packages": packages,
        "transitive_dependencies_audited": False,
        "vulnerabilities_checked": False,
        "lockfile_with_hashes_verified": False,
        "installed_packages_tested": False,
        "release_gate": "BLOCKED_PENDING_LOCK_TRANSITIVE_SECURITY_AUDIT_AND_INSTALLED_TESTS",
        "performed_installation": False,
        "performed_network_request": False,
    }


def auditar(root: Path = ROOT) -> dict:
    root = Path(root)
    files = (root / "pyproject.toml", root / "config/ivo_ferramentas_github.v1.json")
    contents = []
    for path in files:
        if path.is_symlink() or not path.is_file() or path.stat().st_size > 200_000:
            raise ErroDependencias("arquivo de inventário ausente, symlink ou grande demais")
        try:
            contents.append(path.read_text(encoding="utf-8"))
        except UnicodeError as exc:
            raise ErroDependencias("inventário não é UTF-8") from exc
    try:
        ivo = json.loads(contents[1])
    except json.JSONDecodeError as exc:
        raise ErroDependencias("catálogo IVO JSON inválido") from exc
    return inspecionar(contents[0], ivo)


def main() -> int:
    parser = argparse.ArgumentParser(description="Pré-voo estático de dependências NIVON; não instala")
    parser.add_argument("--root", type=Path, default=ROOT)
    args = parser.parse_args()
    try:
        result = auditar(args.root)
    except (ErroDependencias, OSError) as exc:
        parser.exit(2, f"DEPENDENCIAS_BLOQUEADAS: {exc}\n")
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
