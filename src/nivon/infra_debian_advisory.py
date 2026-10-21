"""Confronta CVEs Trivy com dados OFICIAIS Debian Security Tracker (offline).

O CI transfere apenas JSON público Debian de URL fixa; esta unidade não
acessa rede, nunca publica os IDs de CVE ou valores de campos do fornecedor,
não libera release e nunca converte ausência de evidência em 'corrigido'.
"""
from __future__ import annotations

import argparse
from collections import Counter
from datetime import datetime, timezone
import json
from pathlib import Path
import re

from .infra_supplychain import ErroSupplyChain, _carregar_json

TRACKER_URL = "https://security-tracker.debian.org/tracker/data/json"
EXPECTED_IMAGE = "nivon-worker-supply:ci"
CVE = re.compile(r"CVE-[0-9]{4}-[0-9]{4,9}\Z")
SOURCE = re.compile(r"[a-z0-9][a-z0-9+._-]{0,99}\Z")
RELEASE = "trixie"
MAX_TRACKER_BYTES = 25_000_000
OS_STATUSES = ("open", "resolved", "undetermined", "not-affected", "other")
SEVERITIES = ("HIGH", "CRITICAL")


def _tracker_file(path: str | Path) -> dict:
    f = Path(path)
    if f.is_symlink() or not f.is_file() or not 100 < f.stat().st_size <= MAX_TRACKER_BYTES:
        raise ErroSupplyChain("snapshot oficial Debian ausente/inválido/tamanho não homologado")
    # O parser existente recusa JSON com chaves duplicadas.
    return _carregar_json(f)


def _tracker_release(entry: object) -> tuple[str, bool, bool]:
    if not isinstance(entry, dict):
        return ("other", False, False)
    releases = entry.get("releases")
    if not isinstance(releases, dict):
        return ("other", False, False)
    data = releases.get(RELEASE)
    if not isinstance(data, dict):
        return ("other", False, False)
    status = data.get("status")
    if not isinstance(status, str) or status not in OS_STATUSES:
        status = "other"
    fixed = data.get("fixed_version")
    available = isinstance(fixed, str) and bool(fixed.strip()) and not fixed.startswith("<")
    nodsa = data.get("nodsa")
    return status, available, bool(nodsa)


def confrontar(scan: dict, tracker: dict) -> dict:
    """Conta pares (ID CVE, pacote-fonte), nunca confunde 9 binários com 9 CVEs."""
    if not isinstance(scan, dict) or scan.get("SchemaVersion") != 2:
        raise ErroSupplyChain("Trivy com schema ausente")
    if scan.get("ArtifactName") != EXPECTED_IMAGE or scan.get("ArtifactType") != "container_image":
        raise ErroSupplyChain("Trivy não analisou imagem canônica")
    if not isinstance(scan.get("Results"), list) or not scan["Results"]:
        raise ErroSupplyChain("Trivy sem resultados")
    if not isinstance(tracker, dict) or not isinstance(tracker.get("util-linux"), dict):
        raise ErroSupplyChain("snapshot do Debian não contém pacote-fonte de controle")

    os_findings = 0
    lang_findings = 0
    pairs: set[tuple[str, str]] = set()
    missing_source: set[str] = set()
    missing_tracker: set[tuple[str, str]] = set()
    status_by_pair: Counter[str] = Counter()
    matched_with_fix = 0
    matched_nodsa = 0
    all_os_cves: set[str] = set()

    for row in scan["Results"]:
        if not isinstance(row, dict) or row.get("Class") not in ("os-pkgs", "lang-pkgs"):
            raise ErroSupplyChain("classe Trivy desconhecida")
        vulnerabilities = row.get("Vulnerabilities")
        if vulnerabilities is None:
            vulnerabilities = []
        if not isinstance(vulnerabilities, list):
            raise ErroSupplyChain("lista CVE inválida")
        for v in vulnerabilities:
            if not isinstance(v, dict) or v.get("Severity") not in (*SEVERITIES, "LOW", "MEDIUM", "UNKNOWN"):
                raise ErroSupplyChain("registro de severidade inválido")
            if v["Severity"] not in SEVERITIES:
                continue
            if row["Class"] == "lang-pkgs":
                lang_findings += 1
                continue
            os_findings += 1
            identity = v.get("VulnerabilityID")
            if not isinstance(identity, str) or not CVE.fullmatch(identity):
                raise ErroSupplyChain("ID CVE do SO ausente/inesperado")
            all_os_cves.add(identity)
            # Trivy informa SrcName para Debian; PkgName só pode ser usado
            # quando ele próprio é uma entrada fonte do tracker.
            source = v.get("SrcName")
            if not isinstance(source, str) or not SOURCE.fullmatch(source):
                binary_name = v.get("PkgName")
                source = binary_name if isinstance(binary_name, str) and binary_name in tracker else None
            if source is None:
                missing_source.add(identity)
                continue
            pair = (source, identity)
            if pair in pairs:
                continue
            pairs.add(pair)
            package_issues = tracker.get(source)
            if not isinstance(package_issues, dict) or not isinstance(package_issues.get(identity), dict):
                missing_tracker.add(pair)
                continue
            status, has_fixed_version, has_nodsa = _tracker_release(package_issues[identity])
            status_by_pair[status] += 1
            matched_with_fix += int(has_fixed_version)
            matched_nodsa += int(has_nodsa)

    if os_findings == 0:
        raise ErroSupplyChain("sem CVEs HIGH/CRITICAL do SO; não gerar reconciliação artificial")
    matched = sum(status_by_pair.values())
    return {
        "schema": "nivon.infrastructure.debian_advisory_reconciliation.v1",
        "status": "EVIDENCE_REVIEW_REQUIRED",
        "image": EXPECTED_IMAGE,
        "source": "Debian Security Tracker",
        "source_url": TRACKER_URL,
        "release": RELEASE,
        "os_high_critical_findings": os_findings,
        "lang_high_critical_findings": lang_findings,
        "distinct_os_cves": len(all_os_cves),
        "distinct_source_cve_pairs": len(pairs),
        "matched_source_cve_pairs": matched,
        "no_source_mapping_cves": len(missing_source),
        "no_tracker_entry_pairs": len(missing_tracker),
        "vendor_status_by_pair": {s: status_by_pair[s] for s in OS_STATUSES},
        "fixed_version_declared_pairs": matched_with_fix,
        "no_dsa_flagged_pairs": matched_nodsa,
        "package_installed_version_checked": False,
        "vendor_resolved_not_equal_image_fixed": True,
        "no_findings_suppressed": True,
        "release_authorized": False,
    }


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Reconciliar Trivy/Debian Trixie sem liberar release")
    ap.add_argument("--trivy-json", required=True)
    ap.add_argument("--debian-tracker-json", required=True)
    args = ap.parse_args(argv)
    try:
        out = confrontar(_carregar_json(args.trivy_json),
                         _tracker_file(args.debian_tracker_json))
    except (OSError, ValueError) as exc:
        print(json.dumps({"status": "INVALID_OFFICIAL_CROSSCHECK", "reason": str(exc),
                          "release_authorized": False}, sort_keys=True))
        return 2
    out["collection_date_utc"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
    print(json.dumps(out, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
