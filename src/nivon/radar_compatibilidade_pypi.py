"""Cobertura ampla dos NOVE pacotes diretos de extras NIVON por metadados PyPI/OSV.

Protocolo de rede limitado a lista explícita e APIs oficiais: 8 índices JSON
de release + 9 metadados versionados e 1 POST OSV. Nenhum wheel/sdist baixado.
O candidato é a maior versão NUMÉRICA estável não-yanked que satisfaz apenas
um subconjunto de PEP 440; não é lock, resolução transitive ou garantia de
compatibilidade de Python/ABI/plataforma.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import tomllib
from datetime import datetime, timezone
from pathlib import Path

from .auditoria_evidencias_pacotes import ErroEvidencia, _dentro_do_requisito
from .auditoria_extras import ErroDependencias, analisar_requisito, chave_requisito
from .radar_pypi_osv import BloqueioRadar, _parse_json, _release, _osv_results, _request

# Limitador defensivo. Não permitir que um pyproject adulterado dispare
# consultas para centenas de dependências ou endpoints diferentes.
ALLOWED = frozenset({
    "agrobr", "duckdb", "mlforecast", "openpyxl", "pandas",
    "pdfplumber", "river", "scikit-learn", "statsforecast",
})
MAX_INDEX_BYTES = 20 * 1024 * 1024
MAX_RELEASES = 10_000
NUMERIC = re.compile(r"\d+(?:\.\d+){0,3}\Z")


def _requirements(pyproject: str) -> dict:
    try:
        parsed = tomllib.loads(pyproject)["project"]
        if parsed.get("name") != "nivon" or parsed.get("dependencies", []) != []:
            raise BloqueioRadar("projeto ou dependências runtime alterados")
        extras = parsed["optional-dependencies"]
        if not isinstance(extras, dict) or not extras:
            raise BloqueioRadar("extras ausentes")
        result = {}
        for group, items in sorted(extras.items()):
            if not isinstance(group, str) or not isinstance(items, list):
                raise BloqueioRadar("grupo inválido")
            for raw in items:
                req = analisar_requisito(raw)
                name = req["distribution"]
                if name not in ALLOWED:
                    raise BloqueioRadar("pacote fora da allowlist: " + name)
                prior = result.setdefault(name, {"requirement": raw, "parsed": req, "groups": []})
                if chave_requisito(prior["parsed"]) != chave_requisito(req):
                    raise BloqueioRadar("restrições diferentes por extra: " + name)
                prior["groups"].append(group)
        if set(result) != ALLOWED or len(result) != 9:
            raise BloqueioRadar("cobertura de pacotes diretos incompleta")
        return result
    except (TypeError, KeyError, ValueError, tomllib.TOMLDecodeError,
            ErroDependencias) as exc:
        raise BloqueioRadar("manifesto de dependências inválido") from exc


def _numeric_key(version: str) -> tuple[int, int, int, int] | None:
    if not isinstance(version, str) or not NUMERIC.fullmatch(version):
        return None
    parts = [int(i) for i in version.split(".")]
    return tuple((parts + [0] * (4 - len(parts)))[:4])


def _select_candidate(name: str, raw: bytes, parsed: dict) -> dict:
    """Seleção conservadora de versão; exige ao menos um arquivo não yanked.

    Descarta candidatos com PEP 440 fora do subconjunto, prereleases/devs,
    releases sem arquivo, somente yanked ou sem hash SHA256 declarado.
    """
    if not isinstance(raw, bytes) or len(raw) > MAX_INDEX_BYTES:
        raise BloqueioRadar("índice de versões excessivo")
    doc = _parse_json(raw, MAX_INDEX_BYTES)
    info, releases = doc.get("info"), doc.get("releases")
    if (not isinstance(info, dict) or
            not isinstance(info.get("name"), str) or
            re.sub(r"[-_.]+", "-", info["name"].lower()) != name or
            not isinstance(releases, dict) or len(releases) > MAX_RELEASES):
        raise BloqueioRadar("índice PyPI com identidade/estrutura inválida")
    options = []
    for version, files in releases.items():
        key = _numeric_key(version)
        if key is None:
            continue
        try:
            allowed = _dentro_do_requisito(version, parsed)
        except ErroEvidencia:
            allowed = False
        if not allowed:
            continue
        if not isinstance(files, list) or len(files) > 256:
            raise BloqueioRadar("release numérica com quantidade inválida de arquivos")
        healthy = False
        for file in files:
            if not isinstance(file, dict):
                raise BloqueioRadar("arquivo do índice não estruturado")
            if file.get("yanked") is True:
                continue
            digests = file.get("digests")
            if (file.get("packagetype") in ("bdist_wheel", "sdist")
                    and isinstance(digests, dict)
                    and isinstance(digests.get("sha256"), str)
                    and re.fullmatch(r"[a-f0-9]{64}", digests["sha256"])):
                healthy = True
        if healthy:
            options.append((key, version))
    if not options:
        raise BloqueioRadar("sem candidato numérico estável auditável para " + name)
    _, candidate = max(options, key=lambda x: (x[0], x[1]))
    latest = info.get("version")
    if not isinstance(latest, str) or len(latest) > 128:
        raise BloqueioRadar("versão latest PyPI inválida")
    return {
        "name": name,
        "pypi_latest_version": latest,
        "candidate_version": candidate,
        "latest_equals_candidate": candidate == latest,
        "index_sha256": hashlib.sha256(raw).hexdigest(),
        "numeric_stable_eligible_candidates": len(options),
        "candidate_selection": "HIGHEST_SUPPORTED_NUMERIC_NON_YANKED_WITH_HASH_CLAIM",
        "pep440_full_resolution": False,
        "requires_python_evaluated": False,
        "platform_wheel_tag_evaluated": False,
    }


def executar(project_text: str, *, fetch=_request, observed_at: datetime | None = None) -> dict:
    """Somente 8 índices + 9 releases (pin agrobr) + OSV para 9 candidatos.

    A injeção de fetch em testes NUNCA gera evidência classificada como LIVE.
    """
    if not isinstance(project_text, str) or len(project_text.encode()) > 80_000:
        raise BloqueioRadar("manifesto inválido ou excessivo")
    requirements = _requirements(project_text)
    now = observed_at or datetime.now(timezone.utc)
    if not isinstance(now, datetime) or now.tzinfo is None:
        raise BloqueioRadar("data de corte sem timezone")
    picked = []
    for name in sorted(ALLOWED):
        rule = requirements[name]
        pinned = rule["parsed"]["exact_pin"]
        if pinned:
            candidate = next(ver for op, ver in rule["parsed"]["constraints"] if op == "==")
            selection = {
                "name": name, "candidate_version": candidate,
                "pypi_latest_version": None,
                "latest_equals_candidate": None,
                "index_sha256": None,
                "numeric_stable_eligible_candidates": None,
                "candidate_selection": "EXACT_VERSION_DECLARED_IN_PROJECT",
                "pep440_full_resolution": False,
                "requires_python_evaluated": False,
                "platform_wheel_tag_evaluated": False,
            }
        else:
            index_uri = "https://pypi.org/pypi/" + name + "/json"
            selection = _select_candidate(name, fetch(index_uri), rule["parsed"])
        candidate = selection["candidate_version"]
        detail_uri = f"https://pypi.org/pypi/{name}/{candidate}/json"
        details = _release(name, fetch(detail_uri), pinned=candidate)
        if not any(not item["yanked"] for item in details["release_files"]):
            raise BloqueioRadar("candidato não possui arquivos não-yanked: " + name)
        # Exigir o vínculo exato entre o artefato versionado e a faixa declarada.
        if not _dentro_do_requisito(details["version"], rule["parsed"]):
            raise BloqueioRadar("candidato versionado não satisfaz restrição: " + name)
        picked.append({
            **selection, **details,
            "direct_requirement": rule["requirement"],
            "project_extras": sorted(set(rule["groups"])),
            "direct_numeric_range_satisfied": True,
        })
    queries = [
        {"package": {"ecosystem": "PyPI", "name": x["name"]}, "version": x["version"]}
        for x in picked
    ]
    body = json.dumps({"queries": queries}, separators=(",", ":")).encode()
    if len(body) > 32_000:
        raise BloqueioRadar("lote OSV grande demais")
    osv_raw = fetch("https://api.osv.dev/v1/querybatch", body)
    osv = _osv_results(osv_raw, picked)
    pypi_count = sum(
        len(x["pypi_reported_vulnerability_ids"] or []) for x in picked)
    return {
        "schema": "NIVON_ALL_EXTRAS_PYPI_OSV_CANDIDATES_V1",
        "generated_utc": now.astimezone(timezone.utc).isoformat(),
        "source": ("LIVE_PUBLIC_PYPI_AND_OSV_METADATA" if fetch is _request
                   else "INJECTED_RESPONSE_FIXTURES_NOT_LIVE"),
        "direct_distributions_covered": len(picked),
        "optional_extras_covered": sorted({g for p in picked for g in p["project_extras"]}),
        "latest_outside_candidate": [
            {"name": p["name"], "latest": p["pypi_latest_version"],
             "candidate": p["candidate_version"]}
            for p in picked if p["latest_equals_candidate"] is False
        ],
        "packages": picked,
        "osv": osv,
        "osv_total_ids_reported": sum(v["osv_count_reported"] for v in osv),
        "pypi_total_ids_reported": pypi_count,
        "pypi_release_json_requests": len(picked),
        "pypi_index_json_requests": sum(p["index_sha256"] is not None for p in picked),
        "osv_batch_queries": len(queries),
        "metadata_only": True,
        "transitive_dependencies_selected": False,
        "full_pep440_pep508_resolved": False,
        "python_platform_compatibility_verified": False,
        "sha256_claims_checked_against_bytes": False,
        "packages_downloaded": False,
        "packages_installed": False,
        "licenses_legally_approved": False,
        "no_cve_claim": False,
        "approved_for_install": False,
        "approved_for_production": False,
        "release_gate": "BLOCKED_PENDING_TRANSITIVE_RESOLUTION_SIGNED_WHEELS_CVE_LICENSE_RUNTIME",
    }


def main() -> int:
    ap = argparse.ArgumentParser(description="Selecionar candidatos por PyPI para todos os extras, sem instalar")
    ap.add_argument("--pyproject", type=Path, default=Path("pyproject.toml"))
    ap.add_argument("--output", type=Path, required=True)
    args = ap.parse_args()
    try:
        if (args.pyproject.is_symlink() or not args.pyproject.is_file()
                or args.pyproject.stat().st_size > 80_000):
            raise BloqueioRadar("pyproject ausente/grande/symlink")
        data = executar(args.pyproject.read_text(encoding="utf-8"))
        if args.output.is_symlink() or args.output.exists() or not args.output.parent.is_dir():
            raise BloqueioRadar("destino inválido/existente")
        args.output.write_text(json.dumps(data, indent=2, ensure_ascii=False,
                                          sort_keys=True) + "\n", encoding="utf-8")
    except (BloqueioRadar, OSError, UnicodeError) as exc:
        ap.exit(2, f"CANDIDATOS_BLOQUEADOS: {exc}\n")
    print(json.dumps({
        "source": data["source"], "covered": data["direct_distributions_covered"],
        "candidates": {p["name"]: p["candidate_version"] for p in data["packages"]},
        "latest_outside_candidate": data["latest_outside_candidate"],
        "osv_ids": data["osv_total_ids_reported"], "pypi_ids": data["pypi_total_ids_reported"],
        "approved_for_install": False, "approved_for_production": False,
    }, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
