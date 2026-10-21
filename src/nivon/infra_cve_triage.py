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
            if not isinstance(item.get("VulnerabilityID"), str) or not item["VulnerabilityID"].strip():
                raise ErroSupplyChain("identificação da vulnerabilidade ausente")
            kind = row["Class"]
            entry = packages[(kind, name)]
            entry["critical" if item["Severity"] == "CRITICAL" else "high"] += 1
            fix = item.get("FixedVersion")
            if isinstance(fix, str) and fix.strip():
                entry["fix_reported"] += 1
            else:
                entry["no_fix_reported"] += 1
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
