"""Audita exclusivamente scans de imagens CI efêmeras; jamais autoriza release."""
from __future__ import annotations
import argparse
from collections import Counter
import json

from .infra_supplychain import ErroSupplyChain, _carregar_json

ARTIFACTS = {"baseline": "nivon-analytics:baseline", "candidate": "nivon-analytics:ci"}
SEVERITIES = ("UNKNOWN", "LOW", "MEDIUM", "HIGH", "CRITICAL")
EXTRAS = {"agrobr", "pandas", "statsforecast"}


def _contar(scan: dict, image: str) -> dict[str, int]:
    if not isinstance(scan, dict) or scan.get("SchemaVersion") != 2:
        raise ErroSupplyChain("formato do scanner incompatível")
    if scan.get("ArtifactName") != image or scan.get("ArtifactType") != "container_image":
        raise ErroSupplyChain("identidade da imagem de CI diverge")
    targets = scan.get("Results")
    if not isinstance(targets, list) or not targets:
        raise ErroSupplyChain("scanner sem resultados: não afirmar ausência de CVE")
    count = Counter({s: 0 for s in SEVERITIES})
    for row in targets:
        if (not isinstance(row, dict) or row.get("Class") not in ("os-pkgs", "lang-pkgs")
            or not isinstance(row.get("Target"), str) or not row["Target"]):
            raise ErroSupplyChain("alvo da varredura inválido")
        for v in row.get("Vulnerabilities") or []:
            if not isinstance(v, dict) or v.get("Severity") not in SEVERITIES:
                raise ErroSupplyChain("severidade inválida")
            count[v["Severity"]] += 1
    return dict(count)


def auditar(baseline: dict, candidate: dict, bom: dict, arch: str) -> dict:
    if arch not in ("amd64", "arm64"):
        raise ErroSupplyChain("arquitetura não homologada")
    b = _contar(baseline, ARTIFACTS["baseline"])
    c = _contar(candidate, ARTIFACTS["candidate"])
    if not isinstance(bom, dict) or bom.get("bomFormat") != "CycloneDX":
        raise ErroSupplyChain("SBOM não é CycloneDX")
    components = bom.get("components")
    if not isinstance(components, list) or not components:
        raise ErroSupplyChain("SBOM vazio ou incorreto")
    names = {
        x["name"].lower().replace("_", "-")
        for x in components
        if isinstance(x, dict) and isinstance(x.get("name"), str)
    }
    if not EXTRAS.issubset(names):
        raise ErroSupplyChain("SBOM não identifica todos os extras obrigatórios")
    baseline_blockers = b["HIGH"] + b["CRITICAL"]
    candidate_blockers = c["HIGH"] + c["CRITICAL"]
    return {
        "schema": "nivon.infrastructure.analytics_image_audit.v1",
        "architecture": arch, "base_distro": "debian-trixie",
        "base_blocking_findings": baseline_blockers,
        "analytics_blocking_findings": candidate_blockers,
        "additional_blocking_findings": candidate_blockers - baseline_blockers,
        "analytics_high": c["HIGH"], "analytics_critical": c["CRITICAL"],
        "sbom_components": len(components),
        "sbom_includes_all_requested_extras": True,
        "transitive_versions_locked": False,
        "licenses_and_data_permissions_reviewed": False,
        "cve_gate_passed": candidate_blockers == 0,
        "scan_not_sufficient_for_production": True,
        "analytics_image_adopted": False,
        "production_authorized": False,
    }


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Scan offline de imagem analítica experimental")
    p.add_argument("--baseline", required=True)
    p.add_argument("--candidate", required=True)
    p.add_argument("--sbom", required=True)
    p.add_argument("--arch", choices=("amd64", "arm64"), required=True)
    a = p.parse_args(argv)
    try:
        data = auditar(_carregar_json(a.baseline), _carregar_json(a.candidate),
                       _carregar_json(a.sbom), a.arch)
    except (OSError, ValueError):
        print(json.dumps({"status": "INVALID_AUDIT_BLOCKED", "production_authorized": False}))
        return 2
    print(json.dumps(data, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
