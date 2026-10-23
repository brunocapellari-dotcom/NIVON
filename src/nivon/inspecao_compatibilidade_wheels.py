"""Analisa compatibilidade declarada de wheels sem instalar ou baixar bytes.

Alvo explícito: CPython 3.11.0, Linux x86_64, glibc >=2.17 (manylinux2014).
Implementação intencionalmente PARCIAL de wheel tags e Requires-Python:
apenas evidência de metadados remotos, nunca prova de compatibilidade real.
"""
from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

from .radar_pypi_osv import BloqueioRadar

TARGET = "CPython 3.11 / Linux x86_64 / glibc >=2.17"
_PYTHON_VERSION = (3, 11, 0)
_CANON = re.compile(r"[-_.]+")
_NUMERIC = re.compile(r"\d+(?:\.\d+){0,2}\Z")
_SPEC = re.compile(r"(>=|<=|==|!=|>|<)\s*(\d+(?:\.\d+){0,2})\Z")
_MANYLINUX = re.compile(r"manylinux_2_(\d+)_x86_64\Z")
_NAME = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]*\Z")
MAX_FILE_COUNT = 256
MAX_DEPENDENCIES = 512


def _python_range(spec: str | None) -> str:
    """Três estados: match, exclude, unknown. Não é um parser PEP 440."""
    if not isinstance(spec, str) or not spec.strip():
        return "UNKNOWN"
    clauses = [x.strip() for x in spec.split(",")]
    if not clauses or len(clauses) > 16:
        return "UNKNOWN"
    for clause in clauses:
        match = _SPEC.fullmatch(clause)
        if not match:
            return "UNKNOWN"
        op, text = match.groups()
        if not _NUMERIC.fullmatch(text):
            return "UNKNOWN"
        n = tuple(int(x) for x in text.split("."))
        target = _PYTHON_VERSION[:len(n)]
        condition = {
            ">": target > n, ">=": target >= n,
            "<": target < n, "<=": target <= n,
            "==": target == n, "!=": target != n,
        }[op]
        if not condition:
            return "EXCLUDES"
    return "MATCHES"


def _platform(token: str, glibc_minor: int = 17) -> str:
    if token == "any":
        return "MATCHES"
    if token in {"manylinux1_x86_64", "manylinux2010_x86_64",
                 "manylinux2014_x86_64"}:
        return "MATCHES"
    m = _MANYLINUX.fullmatch(token)
    if m and int(m.group(1)) <= glibc_minor:
        return "MATCHES"
    if token == "linux_x86_64":
        # Não há garantia de glibc/ABI para a distro-alvo.
        return "INDETERMINATE"
    return "EXCLUDES"


def _filename_tag(filename: str, name: str, version: str,
                  glibc_minor: int = 17) -> str:
    """Avalia o subconjunto de tags pip/PEP 425 sem assumir tags desconhecidas.

    Compactação por '.' é testada em produto cartesiano com limites estritos.
    """
    if (not isinstance(filename, str) or len(filename) > 255 or
            not filename.endswith(".whl") or "/" in filename or "\\" in filename):
        return "INVALID"
    elements = filename[:-4].split("-")
    if len(elements) not in (5, 6):
        return "INVALID"
    dist, ver = elements[:2]
    if (_CANON.sub("-", dist).lower() != _CANON.sub("-", name).lower()
            or ver != version):
        return "INVALID"
    py, abi, platform = elements[-3:]
    if any(not x or len(x) > 120 for x in (py, abi, platform)):
        return "INVALID"
    pys, abis, plats = py.split("."), abi.split("."), platform.split(".")
    if len(pys)*len(abis)*len(plats) > 200:
        return "INVALID"
    any_indeterminate = False
    for p in pys:
        for a in abis:
            # Executável CPython 3.11. Tag abi3 só funciona se a minimum
            # cpXX <=311; 'cp3' sem minor não é assumido como abi3.
            py_match = (
                (p in {"py3", "py311"} and a == "none") or
                (p == "cp311" and a in {"cp311", "abi3", "none"}) or
                (p in {f"cp3{x}" for x in range(2, 11)} and a == "abi3")
            )
            if not py_match:
                continue
            for plat in plats:
                result = _platform(plat, glibc_minor)
                if result == "MATCHES":
                    return "MATCHES_SUPPORTED_TAG_SUBSET"
                if result == "INDETERMINATE":
                    any_indeterminate = True
    return ("UNKNOWN_NON_PORTABLE_LINUX_TAG" if any_indeterminate
            else "NO_TAG_IN_SUPPORTED_SUBSET")


def _dependencies(declared: list[str] | None) -> dict:
    """Classifica NOMES e marcadores, sem ativar extras nem resolver PEP 508.

    Um marker que menciona extra continua marcado como POSSÍVEL,
    mesmo se envolver OR/AND: não significa que será instalado.
    """
    empty = {
        "requires_dist_present": False,
        "unconditional": [],
        "environment_conditional": [],
        "extra_referenced_conditional": [],
        "conditional_or_extras": [],
        "unparsed": [],
    }
    if declared is None:
        return empty
    if not isinstance(declared, list) or len(declared) > MAX_DEPENDENCIES:
        raise BloqueioRadar("Requires-Dist excessivo")
    direct, env, extra, unparsed = set(), set(), set(), []
    for row in declared:
        if not isinstance(row, str) or len(row) > 512:
            raise BloqueioRadar("Requires-Dist inválido")
        m = re.match(r"\s*([a-zA-Z0-9][a-zA-Z0-9_.-]*)(.*)\Z", row)
        if not m or not _NAME.fullmatch(m.group(1)):
            unparsed.append(row[:100])
            continue
        name = _CANON.sub("-", m.group(1)).lower()
        suffix = m.group(2)
        # Os nomes são rótulos de evidência, NÃO arestas resolvidas.
        if ";" in suffix:
            marker = suffix.split(";", 1)[1]
            if re.search(r"\bextra\b", marker):
                extra.add(name)
            else:
                env.add(name)
        elif "[" in suffix:
            extra.add(name)
        else:
            direct.add(name)
    return {
        "requires_dist_present": True,
        "unconditional": sorted(direct),
        "environment_conditional": sorted(env),
        "extra_referenced_conditional": sorted(extra),
        "conditional_or_extras": sorted(env | extra),
        "unparsed": unparsed,
    }


def analisar(releases: dict, *, glibc_minor: int = 17) -> dict:
    """Consome somente JSON do radar de nove candidatos e não contata a rede."""
    if type(glibc_minor) is not int or not 17 <= glibc_minor <= 40:
        raise BloqueioRadar("baseline glibc Linux fora da política")
    target = f"CPython 3.11 / Linux x86_64 / glibc >=2.{glibc_minor}"
    if (not isinstance(releases, dict) or
            releases.get("schema") != "NIVON_ALL_EXTRAS_PYPI_OSV_CANDIDATES_V1"
            or releases.get("direct_distributions_covered") != 9):
        raise BloqueioRadar("inventário de nove dependências incompleto")
    packages = releases.get("packages")
    if not isinstance(packages, list) or len(packages) != 9:
        raise BloqueioRadar("inventário de releases incompleto")
    if (releases.get("approved_for_install") is not False or
            releases.get("approved_for_production") is not False or
            releases.get("full_pep440_pep508_resolved") is not False or
            releases.get("packages_downloaded") is not False):
        raise BloqueioRadar("inventário falsamente homologado")
    result = []
    seen = set()
    for release in packages:
        if not isinstance(release, dict):
            raise BloqueioRadar("release malformada")
        name, version = release.get("name"), release.get("version")
        if (not isinstance(name, str) or not _NAME.fullmatch(name)
                or not isinstance(version, str) or not version
                or name in seen or
                release.get("candidate_version") != version or
                release.get("direct_numeric_range_satisfied") is not True):
            raise BloqueioRadar("releases duplicadas/incoerentes")
        seen.add(name)
        files = release.get("release_files")
        if (not isinstance(files, list) or not files or len(files) > MAX_FILE_COUNT):
            raise BloqueioRadar("arquivos PyPI insuficientes/excessivos")
        requires = _python_range(release.get("requires_python"))
        compatible = []
        unknown = []
        mismatch = []
        for item in files:
            if not isinstance(item, dict) or not isinstance(item.get("filename"), str):
                raise BloqueioRadar("arquivo de release inválido")
            if item.get("yanked") is not False:
                continue
            if item.get("type") != "bdist_wheel":
                continue
            tag = _filename_tag(item["filename"], name, version, glibc_minor)
            file_py = _python_range(item.get("requires_python") or release.get("requires_python"))
            row = {"filename": item["filename"], "wheel_tag_status": tag,
                   "requires_python_status": file_py}
            if tag == "MATCHES_SUPPORTED_TAG_SUBSET" and file_py == "MATCHES":
                compatible.append(row)
            elif tag == "NO_TAG_IN_SUPPORTED_SUBSET" or file_py == "EXCLUDES" or tag == "INVALID":
                mismatch.append(row)
            else:
                unknown.append(row)
        if requires == "EXCLUDES":
            status = "PYTHON_VERSION_EXCLUDED_BY_RELEASE_METADATA"
        elif compatible:
            status = "WHEEL_TAG_AND_PYTHON_RANGE_MATCH_METADATA_ONLY"
        elif unknown:
            status = "WHEEL_COMPATIBILITY_UNCERTAIN"
        else:
            status = "NO_MATCHING_WHEEL_IN_SUPPORTED_SUBSET"
        result.append({
            "name": name, "candidate_version": version,
            "target": target,
            "requires_python_declared": release.get("requires_python"),
            "release_requires_python_status": requires,
            "wheel_metadata_status": status,
            "matching_wheels": compatible[:20],
            "indeterminate_wheels": unknown[:20],
            "non_matching_wheel_count": len(mismatch),
            "release_file_count": len(files),
            "dependencies_declared": _dependencies(release.get("requires_dist_declared")),
            "wheels_downloaded": False,
            "tags_checked_against_actual_wheel_metadata": False,
            "package_installed_or_tested": False,
        })
    all_names = {x["name"] for x in result}
    direct_required = {
        name for p in result for name in p["dependencies_declared"]["unconditional"]
    }
    conditional_required = {
        name for p in result for name in p["dependencies_declared"]["conditional_or_extras"]
    }
    unresolved = sorted((direct_required | conditional_required) - all_names)
    only_unconditional = sorted(direct_required - all_names)
    env_marked = sorted({
        name for p in result
        for name in p["dependencies_declared"]["environment_conditional"]
    } - all_names)
    extra_marked = sorted({
        name for p in result
        for name in p["dependencies_declared"]["extra_referenced_conditional"]
    } - all_names)
    counts = {}
    for r in result:
        counts[r["wheel_metadata_status"]] = counts.get(r["wheel_metadata_status"], 0) + 1
    return {
        "schema": "NIVON_PYPI_TARGET_WHEEL_TAGS_AUDIT_V1",
        "source_observation_utc": releases.get("generated_utc"),
        "target": target,
        "target_glibc_minor": glibc_minor,
        "packages_examined": len(result),
        "package_status_counts": counts,
        "packages": result,
        "declared_distinct_dependency_names": len(direct_required | conditional_required),
        "declared_unresolved_dependency_names": unresolved,
        "unresolved_unconditional_names": only_unconditional,
        "unresolved_environment_marker_names": env_marked,
        "unresolved_extra_referenced_names": extra_marked,
        "dependencies_classified_without_marker_evaluation": True,
        "requires_dist_markers_evaluated": False,
        "full_pep508_dependency_resolution": False,
        "full_packaging_tags_implementation": False,
        "glibc_abi_runtime_verified": False,
        "wheels_downloaded": False,
        "all_packages_compatible": False,
        "approved_for_install": False,
        "approved_for_production": False,
        "release_gate": "BLOCKED_PENDING_FULL_RESOLVER_WHEEL_HASHES_LICENSE_CVES_RUNTIME",
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Auditar tags de wheel e Requires-Python declarados sem download")
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--glibc-minor", type=int, choices=range(17, 41), default=17,
                        help="Baseline manylinux glibc 2.X (17..40), nao e prova do runner real")
    args = parser.parse_args()
    try:
        if args.input.is_symlink() or not args.input.is_file() or args.input.stat().st_size > 10_000_000:
            raise BloqueioRadar("arquivo de metadados ausente ou inseguro")
        data = json.loads(args.input.read_text(encoding="utf-8"))
        report = analisar(data, glibc_minor=args.glibc_minor)
        if args.output.exists() or args.output.is_symlink() or not args.output.parent.is_dir():
            raise BloqueioRadar("destino existente ou inseguro")
        args.output.write_text(json.dumps(report, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
                               encoding="utf-8")
    except (BloqueioRadar, UnicodeError, OSError, ValueError) as exc:
        parser.exit(2, f"COMPATIBILIDADE_BLOQUEADA: {exc}\n")
    print(json.dumps({
        "packages_examined": report["packages_examined"],
        "target": report["target"],
        "status_counts": report["package_status_counts"],
        "declared_unresolved_dependency_names": report["declared_unresolved_dependency_names"][:35],
        "approved_for_install": False,
    }, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
