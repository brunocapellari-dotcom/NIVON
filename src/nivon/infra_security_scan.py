"""Revisão de cadeia de suprimentos NIVON a partir de relatórios Trivy locais.

Não instala scanners, não aceita URLs, não emite autorização de deploy.
Um relatório limpo é apenas evidência parcial: os demais gates seguem OFF.
"""
from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path


class ErroSecurityReport(ValueError):
    """Resultado inválido; nunca assumir ausência de vulnerabilidades."""


EXPECTED_IMAGE = "nivon-worker-ci:offline"
MAX_REPORT_BYTES = 25_000_000
SEVERITIES = ("UNKNOWN", "LOW", "MEDIUM", "HIGH", "CRITICAL")


def _load(path: str | Path) -> dict:
    f = Path(path)
    if f.is_symlink() or not f.is_file():
        raise ErroSecurityReport("relatório ausente ou simbólico")
    if not 0 < f.stat().st_size <= MAX_REPORT_BYTES:
        raise ErroSecurityReport("relatório vazio ou grande demais")

    def unique(pairs):
        out = {}
        for key, val in pairs:
            if key in out:
                raise ErroSecurityReport("chave JSON repetida")
            out[key] = val
        return out

    try:
        obj = json.loads(f.read_text(encoding="utf-8"), object_pairs_hook=unique)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ErroSecurityReport("arquivo JSON do scanner inválido") from exc
    if not isinstance(obj, dict):
        raise ErroSecurityReport("relatório não é objeto JSON")
    return obj


def avaliar_relatorios(vuln: dict, sbom: dict) -> dict:
    """Falha fechada quando Trivy não analisou imagem ou SBOM inválida."""
    if not isinstance(vuln, dict) or vuln.get("SchemaVersion") != 2:
        raise ErroSecurityReport("schema Trivy esperado v2 ausente")
    if vuln.get("ArtifactName") != EXPECTED_IMAGE or vuln.get("ArtifactType") != "container_image":
        raise ErroSecurityReport("Trivy não validou a imagem esperada")
    if not isinstance(vuln.get("Metadata"), dict):
        raise ErroSecurityReport("metadados de imagem ausentes")
    image_id = vuln["Metadata"].get("ImageID")
    if not isinstance(image_id, str) or not image_id.startswith("sha256:") or len(image_id) != 71:
        raise ErroSecurityReport("imagem sem identificador de digest verificável")
    results = vuln.get("Results")
    if not isinstance(results, list) or not results:
        raise ErroSecurityReport("scanner sem resultados analisáveis")

    counts = Counter({k: 0 for k in SEVERITIES})
    packages = set()
    scanned_targets = 0
    for record in results:
        if not isinstance(record, dict):
            raise ErroSecurityReport("resultado malformado")
        target = record.get("Target")
        if not isinstance(target, str) or not target.strip():
            raise ErroSecurityReport("alvo do scanner ausente")
        if record.get("Class") not in ("os-pkgs", "lang-pkgs"):
            # Arquivo/container não analisado de maneira conhecida.
            raise ErroSecurityReport("classe de relatório não homologada")
        scanned_targets += 1
        issues = record.get("Vulnerabilities")
        if issues is None:
            continue  # Trivy omite a lista quando nenhum CVE encontrado.
        if not isinstance(issues, list):
            raise ErroSecurityReport("Vulnerabilities não é lista")
        for item in issues:
            if not isinstance(item, dict) or item.get("Severity") not in SEVERITIES:
                raise ErroSecurityReport("vulnerabilidade sem severidade conhecida")
            if not isinstance(item.get("VulnerabilityID"), str) or not item["VulnerabilityID"]:
                raise ErroSecurityReport("vulnerabilidade sem identificador")
            if not isinstance(item.get("PkgName"), str) or not item["PkgName"]:
                raise ErroSecurityReport("vulnerabilidade sem pacote")
            counts[item["Severity"]] += 1
            packages.add(item["PkgName"])

    if scanned_targets == 0:
        raise ErroSecurityReport("nenhum alvo efetivamente analisado")
    if not isinstance(sbom, dict) or sbom.get("bomFormat") != "CycloneDX":
        raise ErroSecurityReport("SBOM CycloneDX ausente")
    if not isinstance(sbom.get("specVersion"), str) or not sbom["specVersion"]:
        raise ErroSecurityReport("versão CycloneDX ausente")
    components = sbom.get("components")
    if not isinstance(components, list) or not components:
        raise ErroSecurityReport("SBOM sem componentes")
    for c in components:
        if not isinstance(c, dict) or not isinstance(c.get("name"), str) or not c["name"]:
            raise ErroSecurityReport("componente SBOM inválido")

    blockers = []
    if counts["CRITICAL"] or counts["HIGH"]:
        blockers.append("HIGH_CRITICAL_CVES_REQUIRE_TRIAGE")
    if counts["UNKNOWN"]:
        blockers.append("UNKNOWN_SEVERITIES_REQUIRE_TRIAGE")
    if counts["MEDIUM"]:
        blockers.append("MEDIUM_CVES_REQUIRE_RELEASE_REVIEW")
    # Mesmo com 0 CVEs, aprovação de produção requer mais controles e evidências.
    return {
        "schema": "nivon.security.scan_summary.v1",
        "status": "SCAN_REVIEW_REQUIRED" if blockers else "SCAN_CLEAN_BUT_RELEASE_BLOCKED",
        "image_expected": EXPECTED_IMAGE,
        "image_sha256": image_id,
        "sbom_components": len(components),
        "scanned_targets": scanned_targets,
        "distinct_affected_packages": len(packages),
        "vulnerabilities": dict(counts),
        "review_reasons": blockers,
        "release_authorized": False,
        "production_deploy_authorized": False,
        "source_rights_checked": False,
        "backup_remote_verified": False,
        "ci_supply_chain_safe_guaranteed": False,
    }


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description="Revisão local do relatório Trivy")
    p.add_argument("--vulnerabilities", required=True, help="JSON do Trivy imagem local")
    p.add_argument("--sbom", required=True, help="SBOM CycloneDX gerada pelo scanner")
    p.add_argument("--require-release-ready", action="store_true",
                   help="retorna 3: escopo desta versão NÃO autoriza produção")
    args = p.parse_args(argv)
    try:
        result = avaliar_relatorios(_load(args.vulnerabilities), _load(args.sbom))
        print(json.dumps(result, ensure_ascii=False, sort_keys=True))
        return 3 if args.require_release_ready else 0
    except (ErroSecurityReport, OSError) as exc:
        print(json.dumps({"status": "INVALID_SCAN_BLOCKED", "reason": str(exc),
                          "release_authorized": False}, ensure_ascii=False))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
