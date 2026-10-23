"""Radar REAL, restrito e somente leitura de metadados PyPI + avisos OSV.

Consulta quatro projetos autorizados, sem baixar wheels, executar código,
resolver o grafo, instalar dependências ou declarar homologação. As respostas
são de fontes externas públicas e continuam sujeitas a atraso/incompletude.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import ssl
import tomllib
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

from .auditoria_evidencias_pacotes import ErroEvidencia, _dentro_do_requisito
from .auditoria_extras import analisar_requisito, ErroDependencias

REPO = "brunocapellari-dotcom/NIVON"
PACKAGES = {"agrobr": "agro", "duckdb": "ivo-query",
            "river": "ivo-online", "mlforecast": "ivo-ml"}
MAX_BYTES = 24 * 1024 * 1024
MAX_RESPONSE = 64 * 1024
_SHA = re.compile(r"[a-f0-9]{64}\Z")
_VERSION = re.compile(r"[A-Za-z0-9][A-Za-z0-9._+!-]{0,127}\Z")
_PYPI_NAME = re.compile(r"[a-z0-9]+(?:[-_.][a-z0-9]+)*\Z")


class BloqueioRadar(ErroEvidencia):
    """Falha fechada: rede, índice ou vulnerabilidades incompletos."""


def _parse_json(raw: bytes, max_bytes: int) -> dict:
    if not isinstance(raw, bytes) or len(raw) > max_bytes:
        raise BloqueioRadar("resposta excedeu limite")
    def unique(pairs):
        result = {}
        for k, value in pairs:
            if k in result:
                raise BloqueioRadar("JSON com chaves duplicadas")
            result[k] = value
        return result
    try:
        data = json.loads(raw.decode("utf-8", "strict"), object_pairs_hook=unique)
    except (ValueError, UnicodeError) as exc:
        raise BloqueioRadar("JSON de fonte externa inválido") from exc
    if not isinstance(data, dict):
        raise BloqueioRadar("API não respondeu objeto JSON")
    return data


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, hdr, url):
        raise BloqueioRadar("redirecionamento de fonte externa não permitido")


def _request(endpoint: str, payload: bytes | None = None) -> bytes:
    if endpoint.startswith("https://pypi.org/pypi/"):
        tail = endpoint.removeprefix("https://pypi.org/pypi/")
        if not re.fullmatch(r"[a-z0-9][a-z0-9_.-]{0,63}/(?:[A-Za-z0-9._+!-]{1,128}/)?json", tail):
            raise BloqueioRadar("rota PyPI fora da allowlist")
        if payload is not None:
            raise BloqueioRadar("PyPI não aceita POST no radar")
    elif endpoint == "https://api.osv.dev/v1/querybatch":
        if not isinstance(payload, bytes) or len(payload) > 32_000:
            raise BloqueioRadar("payload OSV inválido ou excessivo")
    else:
        raise BloqueioRadar("host/rota externa não autorizado")
    req = urllib.request.Request(endpoint,
        data=payload,
        headers={
            "Accept": "application/json",
            "Content-Type": "application/json" if payload is not None else "application/octet-stream",
            "User-Agent": "NIVON-Research-Metadata-Only/1.0",
        }, method="POST" if payload is not None else "GET")
    op = urllib.request.build_opener(_NoRedirect)
    try:
        with op.open(req, timeout=12) as response:
            if response.status != 200 or response.geturl() != endpoint:
                raise BloqueioRadar("status/URL de resposta inesperado")
            content = response.read(MAX_BYTES + 1)
    except BloqueioRadar:
        raise
    except (OSError, urllib.error.URLError, TimeoutError, ValueError) as exc:
        raise BloqueioRadar("consulta externa sem sucesso") from exc
    if len(content) > MAX_BYTES:
        raise BloqueioRadar("resposta externa grande demais")
    return content


def _name(value: str) -> str:
    if not isinstance(value, str):
        raise BloqueioRadar("nome de pacote inválido")
    name = re.sub(r"[-_.]+", "-", value.lower())
    if not _PYPI_NAME.fullmatch(name) or len(name) > 64:
        raise BloqueioRadar("nome de pacote não canônico")
    return name


def _project_rules(project_text: str) -> dict:
    try:
        parsed = tomllib.loads(project_text)["project"]
        assert parsed["name"] == "nivon"
        extras = parsed["optional-dependencies"]
        rules = {}
        for pkg, extra in PACKAGES.items():
            req = next(
                (analisar_requisito(r) for r in extras[extra]
                 if _name(r.split(">")[0].split("=")[0].strip()) == pkg),
                None
            )
            if req is None or req["distribution"] != pkg:
                raise BloqueioRadar("dependência monitorada ausente no projeto")
            rules[pkg] = req
        return rules
    except (KeyError, AssertionError, TypeError, ValueError, StopIteration,
            tomllib.TOMLDecodeError, ErroDependencias) as exc:
        raise BloqueioRadar("manifesto de pacotes monitorados não corresponde ao NIVON") from exc


def _release(name: str, response: bytes, *, pinned: str | None = None) -> dict:
    obj = _parse_json(response, MAX_BYTES)
    info = obj.get("info")
    urls = obj.get("urls")
    if not isinstance(info, dict) or not isinstance(urls, list):
        raise BloqueioRadar("release PyPI sem campos obrigatórios")
    version = info.get("version")
    if (_name(info.get("name")) != name or not isinstance(version, str)
            or not _VERSION.fullmatch(version) or
            (pinned is not None and version != pinned)):
        raise BloqueioRadar("identidade ou versão de release PyPI divergente")
    if not urls or len(urls) > 128:
        raise BloqueioRadar("release sem distribuições auditáveis")
    files = []
    for item in urls:
        if not isinstance(item, dict):
            raise BloqueioRadar("arquivo PyPI inválido")
        filename, filetype = item.get("filename"), item.get("packagetype")
        sha = item.get("digests", {}).get("sha256") if isinstance(item.get("digests"), dict) else None
        if (not isinstance(filename, str) or not filename or
                len(filename) > 255 or "/" in filename or "\\" in filename
                or not isinstance(sha, str) or not _SHA.fullmatch(sha)
                or filetype not in ("bdist_wheel", "sdist") or
                type(item.get("yanked")) is not bool):
            raise BloqueioRadar("distribuição PyPI sem hash/nome/tipo válido")
        file_requires = item.get("requires_python")
        if file_requires is not None and (
            not isinstance(file_requires, str) or len(file_requires) > 256
        ):
            raise BloqueioRadar("Requires-Python de arquivo inválido")
        files.append({
            "filename": filename, "sha256_official_claim": sha,
            "type": filetype, "yanked": item["yanked"],
            "requires_python": file_requires,
            "upload_time_iso_8601": item.get("upload_time_iso_8601"),
        })
    expr = info.get("license_expression")
    declared_license = expr if isinstance(expr, str) and expr else None
    legacy_license = info.get("license")
    declared = info.get("requires_dist")
    if declared is not None and (
        not isinstance(declared, list) or len(declared) > 512 or
        any(not isinstance(r, str) or len(r) > 512 for r in declared)
    ):
        raise BloqueioRadar("Requires-Dist do PyPI inválido/excessivo")
    if declared_license is not None and len(declared_license) > 512:
        raise BloqueioRadar("License-Expression extensa")
    pypi_advisories = obj.get("vulnerabilities")
    pypi_ids = None
    if pypi_advisories is not None:
        if not isinstance(pypi_advisories, list) or len(pypi_advisories) > 2000:
            raise BloqueioRadar("lista de vulnerabilidades PyPI inválida")
        pypi_ids = []
        for advisory in pypi_advisories:
            if (not isinstance(advisory, dict) or
                    not isinstance(advisory.get("id"), str) or
                    not advisory["id"] or len(advisory["id"]) > 128):
                raise BloqueioRadar("aviso PyPI sem ID válido")
            pypi_ids.append(advisory["id"])
    return {
        "name": name, "version": version,
        "pypi_raw_response_sha256": hashlib.sha256(response).hexdigest(),
        "pypi_last_serial": obj.get("last_serial"),
        "release_files": sorted(files, key=lambda x: x["filename"]),
        "files_have_yanked": any(f["yanked"] for f in files),
        "license_expression_declared_not_validated": declared_license,
        "legacy_license_present": isinstance(legacy_license, str) and bool(legacy_license.strip()),
        "requires_python": info.get("requires_python"),
        "requires_dist_declared": declared,
        "pypi_reported_vulnerability_ids": (
            sorted(set(pypi_ids)) if pypi_ids is not None else None
        ),
        "pypi_vulnerability_list_in_response": pypi_ids is not None,
        "release_wheel_bytes_downloaded": False,
        "release_hashes_verified_against_downloads": False,
    }


def _osv_results(raw: bytes, expected: list[dict]) -> list[dict]:
    obj = _parse_json(raw, MAX_BYTES)
    results = obj.get("results")
    if not isinstance(results, list) or len(results) != len(expected):
        raise BloqueioRadar("resposta OSV com cardinalidade diferente da consulta")
    out = []
    for item, candidate in zip(results, expected):
        if not isinstance(item, dict) or "next_page_token" in item:
            raise BloqueioRadar("OSV paginou ou respondeu item inválido; resultado incompleto")
        vulns = item.get("vulns", [])
        if not isinstance(vulns, list) or len(vulns) > 1000:
            raise BloqueioRadar("lista OSV de avisos inválida")
        ids = []
        for vuln in vulns:
            if not isinstance(vuln, dict) or not isinstance(vuln.get("id"), str):
                raise BloqueioRadar("aviso OSV sem ID")
            ids.append(vuln["id"])
        out.append({
            "name": candidate["name"], "version": candidate["version"],
            "osv_vulnerability_ids_reported": sorted(set(ids)),
            "osv_count_reported": len(set(ids)),
            "osv_no_reports_at_query_time": len(ids) == 0,
        })
    return out


def executar(project_text: str, *, pypi_fetch=_request, osv_fetch=_request,
             now: datetime | None = None) -> dict:
    """Consulta EXATAMENTE 4 releases PyPI e 1 OSV querybatch, em ordem fixa."""
    rules = _project_rules(project_text)
    observed = now or datetime.now(timezone.utc)
    if not isinstance(observed, datetime) or observed.tzinfo is None:
        raise BloqueioRadar("data de execução sem timezone")
    packages = []
    for name in sorted(PACKAGES):
        req = rules[name]
        pinned = next((v for op, v in req["constraints"] if op == "=="), None)
        uri = ("https://pypi.org/pypi/" + name + "/" +
               (pinned + "/" if pinned else "") + "json")
        raw = pypi_fetch(uri)
        item = _release(name, raw, pinned=pinned)
        # A seleção 'latest' não prova elegibilidade para extras da aplicação.
        item["project_extra"] = PACKAGES[name]
        item["project_declared_requirement"] = next(
            x for x in tomllib.loads(project_text)["project"]["optional-dependencies"][PACKAGES[name]]
            if _name(x.split(">")[0].split("=")[0].strip()) == name)
        try:
            compatible = _dentro_do_requisito(item["version"], req)
        except ErroEvidencia:
            compatible = None
        item["latest_satisfies_supported_numeric_requirement"] = compatible
        item["constraint_status"] = (
            "LATEST_WITHIN_DECLARED_NUMERIC_RANGE" if compatible is True else
            "LATEST_OUTSIDE_DECLARED_NUMERIC_RANGE" if compatible is False else
            "VERSION_REQUIRES_FULL_PEP440_RESOLVER"
        )
        packages.append(item)
    queries = [
        {"package": {"ecosystem": "PyPI", "name": p["name"]},
         "version": p["version"]}
        for p in packages
    ]
    body = json.dumps({"queries": queries}, separators=(",", ":")).encode("utf-8")
    osv_raw = osv_fetch("https://api.osv.dev/v1/querybatch", body)
    vulnerabilities = _osv_results(osv_raw, packages)
    return {
        "schema": "NIVON_PYPI_OSV_READ_ONLY_V1",
        "generated_utc": observed.astimezone(timezone.utc).isoformat(),
        "source_registry": [
            "https://docs.pypi.org/api/json/",
            "https://google.github.io/osv.dev/post-v1-querybatch/",
        ],
        "source": (
            "OFFICIAL_PUBLIC_METADATA_APIS"
            if pypi_fetch is _request and osv_fetch is _request
            else "MOCKED_OR_INJECTED_API_RESPONSE"
        ),
        "scope": "FOUR_SELECTED_DIRECT_DEPENDENCIES_ONLY",
        "pypi_responses_verified_https": pypi_fetch is _request,
        "osv_response_verified_https": osv_fetch is _request,
        "osv_raw_response_sha256": hashlib.sha256(osv_raw).hexdigest(),
        "packages": packages,
        "osv": vulnerabilities,
        "queried_package_count": len(packages),
        "latest_outside_declared_range": [
            p["name"] for p in packages
            if p["latest_satisfies_supported_numeric_requirement"] is False
        ],
        "latest_range_not_evaluable": [
            p["name"] for p in packages
            if p["latest_satisfies_supported_numeric_requirement"] is None
        ],
        "osv_total_ids_reported": sum(x["osv_count_reported"] for x in vulnerabilities),
        "pypi_total_ids_reported": sum(
            len(p["pypi_reported_vulnerability_ids"] or []) for p in packages
        ),
        "pypi_packages_with_vulnerability_field": sum(
            p["pypi_vulnerability_list_in_response"] for p in packages
        ),
        "full_dependency_resolution": False,
        "all_optional_extras_covered": False,
        "wheel_bytes_downloaded": False,
        "wheels_installed": False,
        "actual_wheel_contents_inspected": False,
        "osv_complete_universe_of_cves_proven": False,
        "legal_license_review_completed": False,
        "github_signature_verified": False,
        "approved_for_install": False,
        "approved_for_production": False,
        "release_gate": "BLOCKED_METADATA_RADAR_ONLY_FULL_RESOLUTION_AND_PROVENANCE_REQUIRED",
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Radar PyPI+OSV, leitura pública sem pacotes")
    parser.add_argument("--pyproject", type=Path, default=Path("pyproject.toml"))
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    try:
        if args.pyproject.is_symlink() or not args.pyproject.is_file() or args.pyproject.stat().st_size > 80_000:
            raise BloqueioRadar("pyproject inválido")
        text = args.pyproject.read_text(encoding="utf-8")
        result = executar(text)
        if args.output.exists() or args.output.is_symlink():
            raise BloqueioRadar("arquivo destino já existe; não sobrescrever")
        if not args.output.parent.is_dir() or args.output.parent.is_symlink():
            raise BloqueioRadar("diretório de saída inexistente/inseguro")
        args.output.write_text(json.dumps(result, ensure_ascii=False,
                                         indent=2, sort_keys=True) + "\n", encoding="utf-8")
    except (BloqueioRadar, OSError, UnicodeError) as exc:
        parser.exit(2, f"RADAR_BLOQUEADO: {exc}\n")
    print(json.dumps({
        "project": "NIVON", "source": result["source"],
        "queried_package_count": result["queried_package_count"],
        "versions": {item["name"]: item["version"] for item in result["packages"]},
        "latest_outside_declared_range": result["latest_outside_declared_range"],
        "reported_osv_ids": result["osv_total_ids_reported"],
        "approved_for_production": False,
        "result_file": str(args.output),
    }, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
