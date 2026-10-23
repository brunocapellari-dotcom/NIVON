"""Triagem segura de vulnerabilidades de imagem (somente dados agregados).

Requer relatório Trivy real da imagem de homologação. Não libera produção,
não chama redes, não instala pacotes e nunca imprime IDs de CVE ou caminhos.
Uma FixedVersion é apenas informação do scanner, não correção instalada.
"""
from __future__ import annotations

import argparse
from collections import defaultdict
import json
import re

from .infra_supplychain import ErroSupplyChain, _carregar_json


EXPECTED_IMAGE = "nivon-worker-supply:ci"
SEVERITIES = {"UNKNOWN", "LOW", "MEDIUM", "HIGH", "CRITICAL"}
PACKAGE = re.compile(r"[A-Za-z0-9][A-Za-z0-9.+:_-]{0,119}\Z")
MAX_ISSUES = 100_000
MAX_PACKAGES = 5_000
VULNERABILITY_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.:-]{1,127}\Z")


def triar_vulnerabilidades(scan: dict) -> dict:
    """Priorizar componentes para investigação sem tratar o resultado como waiver."""
    if not isinstance(scan, dict) or scan.get("SchemaVersion") != 2:
        raise ErroSupplyChain("schema Trivy incompatível para triagem")
    if scan.get("ArtifactName") != EXPECTED_IMAGE or scan.get("ArtifactType") != "container_image":
        raise ErroSupplyChain("triagem exige a imagem de homologação específica")
    results = scan.get("Results")
    if not isinstance(results, list) or not results:
        raise ErroSupplyChain("scanner sem alvos: diagnóstico indisponível")

    packages: dict[tuple[str, str], dict[str, int | str]] = defaultdict(
        lambda: {"critical": 0, "high": 0, "fix_reported": 0, "no_fix_reported": 0}
    )
    inspected = 0
    issues_seen = 0
    # Agrupar a mesma vulnerabilidade em varios pacotes nao a elimina do gate:
    # o numero de achados continua sendo contado integralmente.
    distinct: dict[str, dict] = {} 
    by_class = {"os-pkgs": 0, "lang-pkgs": 0}
    for row in results:
        if not isinstance(row, dict) or row.get("Class") not in ("os-pkgs", "lang-pkgs"):
            raise ErroSupplyChain("classe de resultados ausente ou não homologada")
        if not isinstance(row.get("Target"), str) or not row["Target"]:
            raise ErroSupplyChain("alvo do Trivy ausente")
        inspected += 1
        issues = row.get("Vulnerabilities")
        if issues is None:
            issues = []
        if not isinstance(issues, list):
            raise ErroSupplyChain("Vulnerabilities não é lista")
        issues_seen += len(issues)
        if issues_seen > MAX_ISSUES:
            raise ErroSupplyChain("relatório acima do limite de achados")
        for item in issues:
            if not isinstance(item, dict) or item.get("Severity") not in SEVERITIES:
                raise ErroSupplyChain("severidade não homologada")
            if item["Severity"] not in ("HIGH", "CRITICAL"):
                continue
            name = item.get("PkgName")
            if not isinstance(name, str) or not PACKAGE.fullmatch(name):
                raise ErroSupplyChain("nome de pacote não seguro ou ausente")
            identifier = item.get("VulnerabilityID")
            if not isinstance(identifier, str) or not VULNERABILITY_ID.fullmatch(identifier):
                raise ErroSupplyChain("identificador de vulnerabilidade inválido")
            kind = row["Class"]
            by_class[kind] += 1
            entry = packages[(kind, name)]
            entry["critical" if item["Severity"] == "CRITICAL" else "high"] += 1
            fix = item.get("FixedVersion")
            fix_indicated = isinstance(fix, str) and bool(fix.strip())
            if fix_indicated:
                entry["fix_reported"] += 1
            else:
                entry["no_fix_reported"] += 1
            if identifier not in distinct:
                distinct[identifier] = {"affected": set(), "findings": 0,
                                        "fix_indicated": 0, "high": 0, "critical": 0}
            cluster = distinct[identifier]
            cluster["affected"].add((kind, name))
            cluster["findings"] += 1
            cluster["fix_indicated"] += int(fix_indicated)
            cluster["critical" if item["Severity"] == "CRITICAL" else "high"] += 1
            if len(packages) > MAX_PACKAGES:
                raise ErroSupplyChain("limite de pacotes excedido")

    sorted_packages = sorted(packages.items(), key=lambda pair: (
        -pair[1]["critical"], -pair[1]["high"], -pair[1]["fix_reported"],
        pair[0][0], pair[0][1]
    ))
    total_high = sum(v["high"] for v in packages.values())
    total_critical = sum(v["critical"] for v in packages.values())
    with_fix = sum(v["fix_reported"] for v in packages.values())
    without_fix = sum(v["no_fix_reported"] for v in packages.values())
    grouped = sorted(distinct.values(), key=lambda c: (
        -len(c["affected"]), -c["findings"], -c["critical"], -c["high"]
    ))
    # Indicadores de grupos sem publicar IDs, hashes ou caminhos de arquivo.
    # A contagem de IDs distintos nao substitui a contagem de achados.
    repeated = sum(1 for c in grouped if len(c["affected"]) > 1)

    return {
        "schema": "nivon.infrastructure.cve_triage.v1",
        "status": "REMEDIATION_REQUIRED" if total_high + total_critical else "NO_HIGH_CRITICAL_REPORTED",
        "artifact": EXPECTED_IMAGE,
        "scanned_targets": inspected,
        "issues_total": issues_seen,
        "blocking_findings": total_high + total_critical,
        "high": total_high,
        "critical": total_critical,
        "fixed_version_reported": with_fix,
        "no_fixed_version_reported": without_fix,
        "affected_packages": len(packages),
        "distinct_vulnerability_ids": len(distinct),
        "repeated_findings_vs_distinct_ids": total_high + total_critical - len(distinct),
        "ids_affecting_multiple_packages": repeated,
        "blocking_by_package_class": by_class,
        "largest_shared_vulnerability_groups": [
            {"affected_packages": len(c["affected"]),
             "findings": c["findings"],
             "high": c["high"], "critical": c["critical"],
             "fixed_version_reported": c["fix_indicated"]}
            for c in grouped[:10]
        ],
        "shared_groups_truncated": len(grouped) > 10,
        "top_packages": [
            {"kind": kind, "package": name, **counts}
            for (kind, name), counts in sorted_packages[:25]
        ],
        "top_packages_truncated": len(packages) > 25,
        "scan_is_not_proof_of_fix": True,
        "production_authorized": False,
        "release_gate_unchanged": True,
    }


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Triagem offline CVEs altas/críticas")
    ap.add_argument("--trivy-json", required=True)
    args = ap.parse_args(argv)
    try:
        result = triar_vulnerabilidades(_carregar_json(args.trivy_json))
    except (OSError, ValueError) as exc:
        print(json.dumps({"status": "INVALID_TRIAGE_BLOCKED", "reason": str(exc),
                          "production_authorized": False}, ensure_ascii=False))
        return 2
    print(json.dumps(result, sort_keys=True, ensure_ascii=False))
    return 0  # Somente triagem; o gate de Trivy reprova CVEs em passo posterior.


if __name__ == "__main__":
    raise SystemExit(main())
