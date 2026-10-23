"""Benchmark offline de superfícies de CVEs em duas imagens sintéticas.

Não é gate de release nem autorizador de implantação. Compara apenas o
mesmo scanner/banco de CVEs na mesma execução e resiste a relatórios vazios.
"""
from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path


class ErroBenchmark(ValueError):
    pass


PREFIX = "nivon-worker-benchmark:"
SEVERITIES = ("UNKNOWN", "LOW", "MEDIUM", "HIGH", "CRITICAL")
LIMIT = 25_000_000


def ler(relatorio: str | Path) -> dict:
    p = Path(relatorio)
    if p.is_symlink() or not p.is_file() or not 0 < p.stat().st_size <= LIMIT:
        raise ErroBenchmark("relatório ausente ou inválido")

    def sem_repeticoes(pares):
        obj = {}
        for chave, valor in pares:
            if chave in obj:
                raise ErroBenchmark("JSON com chaves duplicadas")
            obj[chave] = valor
        return obj

    try:
        with p.open("r", encoding="utf-8") as fh:
            out = json.load(fh, object_pairs_hook=sem_repeticoes)
    except (OSError, ValueError, UnicodeError) as exc:
        raise ErroBenchmark("JSON de benchmark ilegível") from exc
    if not isinstance(out, dict):
        raise ErroBenchmark("relatório malformado")
    return out


def contar(scan: dict, *, imagem: str) -> dict:
    if imagem not in (PREFIX + "bookworm", PREFIX + "trixie"):
        raise ErroBenchmark("imagem não aprovada para comparação")
    if not isinstance(scan, dict) or scan.get("SchemaVersion") != 2:
        raise ErroBenchmark("schema de scanner não reconhecido")
    if scan.get("ArtifactName") != imagem or scan.get("ArtifactType") != "container_image":
        raise ErroBenchmark("scan de artefato diferente do esperado")
    results = scan.get("Results")
    if not isinstance(results, list) or not results:
        raise ErroBenchmark("scan vazio: não inferir ausência de CVEs")
    counts = Counter({s: 0 for s in SEVERITIES})
    for row in results:
        if not isinstance(row, dict) or not isinstance(row.get("Target"), str) or not row["Target"]:
            raise ErroBenchmark("alvo desconhecido")
        issues = row.get("Vulnerabilities", [])
        if issues is None:
            issues = []
        if not isinstance(issues, list):
            raise ErroBenchmark("lista CVE inválida")
        for issue in issues:
            if not isinstance(issue, dict) or issue.get("Severity") not in SEVERITIES:
                raise ErroBenchmark("severidade CVE desconhecida")
            counts[issue["Severity"]] += 1
    return dict(counts)


def comparar(bookworm: dict, trixie: dict) -> dict:
    base = contar(bookworm, imagem=PREFIX + "bookworm")
    alt = contar(trixie, imagem=PREFIX + "trixie")
    bloqueios_base = base["HIGH"] + base["CRITICAL"]
    bloqueios_alt = alt["HIGH"] + alt["CRITICAL"]
    return {
        "schema": "nivon.infrastructure.base_benchmark.v1",
        "base": base,
        "candidate": alt,
        "high_critical_base": bloqueios_base,
        "high_critical_candidate": bloqueios_alt,
        "delta_high_critical": bloqueios_alt - bloqueios_base,
        "candidate_has_fewer_blockers": bloqueios_alt < bloqueios_base,
        "baseline_approved": False,
        "candidate_approved": False,
        "production_release_allowed": False,
        "next_gate": "INDEPENDENT_CVE_REVIEW_AND_ARM64_RUNTIME_TEST",
    }


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Benchmark de CVEs, não release")
    ap.add_argument("--bookworm", required=True)
    ap.add_argument("--trixie", required=True)
    args = ap.parse_args(argv)
    try:
        result = comparar(ler(args.bookworm), ler(args.trixie))
    except (OSError, ErroBenchmark) as exc:
        print(json.dumps({"status": "INVALID_BENCHMARK", "reason": str(exc),
                          "production_release_allowed": False}, sort_keys=True))
        return 2
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
