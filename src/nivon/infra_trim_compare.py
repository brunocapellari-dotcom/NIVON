"""Compara imagens idênticas antes/depois de remover packaging Python.

Ensaios AMD64/ARM64 de CI. Comparar CVEs não comprova execução de runtime.
"""
from __future__ import annotations

import argparse
from collections import Counter
import json

from .infra_supplychain import ErroSupplyChain, _carregar_json

NAMES = {"base": "nivon-worker-trim:baseline", "trim": "nivon-worker-trim:candidate"}
SEVERITIES = ("UNKNOWN", "LOW", "MEDIUM", "HIGH", "CRITICAL")


def contar(scan: dict, *, name: str) -> dict:
    if name not in NAMES.values():
        raise ErroSupplyChain("imagem não autorizada para ensaio")
    if not isinstance(scan, dict) or scan.get("SchemaVersion") != 2:
        raise ErroSupplyChain("schema do scan inválido")
    if scan.get("ArtifactName") != name or scan.get("ArtifactType") != "container_image":
        raise ErroSupplyChain("relatório diverge da imagem de ensaio")
    results = scan.get("Results")
    if not isinstance(results, list) or not results:
        raise ErroSupplyChain("scan sem alvos: não presumir ausência de CVEs")
    counts = Counter({sev: 0 for sev in SEVERITIES})
    for target in results:
        if (not isinstance(target, dict)
            or target.get("Class") not in ("os-pkgs", "lang-pkgs")
            or not isinstance(target.get("Target"), str)
            or not target["Target"]):
            raise ErroSupplyChain("alvo do scan não homologado")
        vulns = target.get("Vulnerabilities")
        if vulns is None:
            continue
        if not isinstance(vulns, list):
            raise ErroSupplyChain("lista de achados inválida")
        for vuln in vulns:
            if not isinstance(vuln, dict) or vuln.get("Severity") not in SEVERITIES:
                raise ErroSupplyChain("severidade desconhecida")
            counts[vuln["Severity"]] += 1
    return dict(counts)


def comparar(baseline: dict, trimmed: dict, *, architecture: str = "amd64") -> dict:
    if architecture not in ("amd64", "arm64"):
        raise ErroSupplyChain("arquitetura do scanner não permitida")
    before = contar(baseline, name=NAMES["base"])
    after = contar(trimmed, name=NAMES["trim"])
    initial = before["HIGH"] + before["CRITICAL"]
    remaining = after["HIGH"] + after["CRITICAL"]
    return {
        "schema": "nivon.infrastructure.trim_experiment.v1",
        "before": before,
        "after": after,
        "blockers_before": initial,
        "blockers_after": remaining,
        "delta_blockers": remaining - initial,
        "candidate_reduces_blockers": remaining < initial,
        "scan_architecture": architecture,
        "candidate_amd64_only": architecture == "amd64",
        # O parser dos JSONs não atesta execução nativa; isso é prova separada do CI.
        "arm64_runtime_validated": False,
        "candidate_adopted": False,
        "production_allowed": False,
    }


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Experimento de remoção do pip; sem release")
    p.add_argument("--baseline", required=True)
    p.add_argument("--candidate", required=True)
    p.add_argument("--architecture", choices=("amd64", "arm64"), default="amd64")
    a = p.parse_args(argv)
    try:
        r = comparar(_carregar_json(a.baseline), _carregar_json(a.candidate), architecture=a.architecture)
    except (OSError, ValueError) as exc:
        print(json.dumps({"status": "INVALID_TRIM_EXPERIMENT", "reason": str(exc),
                          "production_allowed": False}, sort_keys=True))
        return 2
    print(json.dumps(r, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
