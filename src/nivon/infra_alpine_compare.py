"""Compara Debian Trixie e Alpine com Trivy, sem inferir produção apta."""
from __future__ import annotations

import argparse
from collections import Counter
import json

from .infra_supplychain import ErroSupplyChain, _carregar_json

NAMES = ("nivon-worker-distro:trixie", "nivon-worker-distro:alpine")
SEVERITIES = ("UNKNOWN", "LOW", "MEDIUM", "HIGH", "CRITICAL")


def contar(scan: dict, *, image: str) -> dict:
    if image not in NAMES:
        raise ErroSupplyChain("imagem de experimento não homologada")
    if not isinstance(scan, dict) or scan.get("SchemaVersion") != 2:
        raise ErroSupplyChain("schema Trivy não aceito")
    if scan.get("ArtifactName") != image or scan.get("ArtifactType") != "container_image":
        raise ErroSupplyChain("identidade da imagem divergente")
    rows = scan.get("Results")
    if not isinstance(rows, list) or not rows:
        raise ErroSupplyChain("sem resultados do scanner")
    values = Counter({s: 0 for s in SEVERITIES})
    for row in rows:
        if (not isinstance(row, dict) or row.get("Class") not in ("os-pkgs", "lang-pkgs")
            or not isinstance(row.get("Target"), str) or not row["Target"]):
            raise ErroSupplyChain("alvo do scanner inválido")
        issues = row.get("Vulnerabilities")
        if issues is None:
            issues = []
        if not isinstance(issues, list):
            raise ErroSupplyChain("lista de vulnerabilidades inválida")
        for issue in issues:
            if not isinstance(issue, dict) or issue.get("Severity") not in SEVERITIES:
                raise ErroSupplyChain("severidade de vulnerabilidade desconhecida")
            values[issue["Severity"]] += 1
    return dict(values)


def avaliar(debian: dict, alpine: dict, sbom: dict, architecture: str) -> dict:
    if architecture not in ("amd64", "arm64"):
        raise ErroSupplyChain("arquitetura não homologada")
    before = contar(debian, image=NAMES[0])
    after = contar(alpine, image=NAMES[1])
    if not isinstance(sbom, dict) or sbom.get("bomFormat") != "CycloneDX":
        raise ErroSupplyChain("inventário de componentes não é CycloneDX")
    if not isinstance(sbom.get("specVersion"), str) or not sbom["specVersion"]:
        raise ErroSupplyChain("versão do SBOM ausente")
    components = sbom.get("components")
    if not isinstance(components, list) or not components:
        raise ErroSupplyChain("SBOM vazio, sem prova de cobertura")
    if any(not isinstance(c, dict) or not isinstance(c.get("name"), str)
           or not c["name"] for c in components):
        raise ErroSupplyChain("componente inválido do SBOM")
    previous = before["HIGH"] + before["CRITICAL"]
    current = after["HIGH"] + after["CRITICAL"]
    return {
        "schema": "nivon.infrastructure.alpine_comparison.v1",
        "architecture_of_scan": architecture,
        "debian_trixie": before,
        "alpine_3_23": after,
        "debian_blocking_findings": previous,
        "alpine_blocking_findings": current,
        "delta_blocking_findings": current - previous,
        "alpine_has_fewer_findings": current < previous,
        "alpine_sbom_components": len(components),
        "glibc_to_musl_compatibility_approved": False,
        "image_approved": False,
        "independent_review_completed": False,
        "production_authorized": False,
        "no_cve_waivers": True,
    }


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Comparação estática Debian x Alpine, sem release")
    p.add_argument("--debian-json", required=True)
    p.add_argument("--alpine-json", required=True)
    p.add_argument("--alpine-sbom", required=True)
    p.add_argument("--architecture", choices=["amd64", "arm64"], required=True)
    a = p.parse_args(argv)
    try:
        result = avaliar(_carregar_json(a.debian_json),
                         _carregar_json(a.alpine_json),
                         _carregar_json(a.alpine_sbom),
                         a.architecture)
    except (OSError, ValueError) as exc:
        print(json.dumps({"status": "INVALID_EXPERIMENT",
                          "reason": str(exc), "production_authorized": False}))
        return 2
    print(json.dumps(result, sort_keys=True))
    return 0  # Só analisa; o gate de segurança da imagem principal continua separado.


if __name__ == "__main__":
    raise SystemExit(main())
