"""Gate integrado OFFLINE: relatório pip-audit + lock + bytes locais de wheels.

Cada verificação mantém seu próprio contrato. Consistência não equivale a
autenticidade, resolução das transitivas, CVE real ou permissão de instalação.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from datetime import datetime
from pathlib import Path

from .auditoria_evidencias_pacotes import (
    ErroEvidencia, _arquivo, _json_seguro, avaliar,
)
from .auditoria_wheelhouse import verificar
from .auditoria_fechamento_pacotes import analisar_fechamento
from .auditoria_licencas_pacotes import inventariar_licencas


def verificar_cadeia(
    pyproject: str, lock: str, report: str, metadata: dict, wheelhouse: Path,
    *, agora: datetime | None = None,
) -> dict:
    """Exige dois gates independentes sobre o MESMO lock, antes de reportar.

    Não declara origem dos artefatos (os hashes do metadata são fornecidos
    pelo operador), nem verifica grafo de dependências transitivas.
    """
    report_gate = avaliar(pyproject, lock, report, metadata, agora=agora)
    wheel_gate = verificar(wheelhouse, lock)
    graph_gate = analisar_fechamento(pyproject, lock, wheel_gate,
                                    report_gate["selected_extras"])
    license_gate = inventariar_licencas(wheel_gate)
    if report_gate["locked_packages"] != wheel_gate["wheel_count"]:
        raise ErroEvidencia("gates não concordam sobre quantidade de distribuições")
    if not all(
        (
            report_gate["approved_for_production"] is False,
            report_gate["transitive_dependency_closure_verified"] is False,
            wheel_gate["approved_for_production"] is False,
            wheel_gate["dependency_closure_verified"] is False,
        )
    ):
        raise ErroEvidencia("estado de segurança incompatível com gate offline")
    return {
        "project": "NIVON",
        "evidence_type": "OFFLINE_COHERENCE_AND_LOCAL_WHEEL_SHA256",
        "pyproject_sha256": hashlib.sha256(pyproject.encode("utf-8")).hexdigest(),
        "lock_sha256": hashlib.sha256(lock.encode("utf-8")).hexdigest(),
        "report_sha256": hashlib.sha256(report.encode("utf-8")).hexdigest(),
        "selected_extras": report_gate["selected_extras"],
        "wheels_hash_verified": wheel_gate["wheel_count"],
        "direct_packages_checked": report_gate["direct_packages_covered"],
        "reported_vulnerabilities": report_gate["vulnerabilities_reported"],
        "reported_no_vulnerabilities": report_gate["reported_no_vulnerabilities"],
        "lock_report_coherent": True,
        "local_wheel_hashes_match_declared_lock": True,
        "wheel_metadata_identity_checked": True,
        "supported_wheel_dependencies_checked": graph_gate["declared_edges_checked"],
        "supported_wheel_dependencies_consistent": graph_gate[
            "unconditional_supported_requirements_consistent"],
        "all_pep508_requirements_supported": False,
        "resolver_transitive_closure_attested": False,
        "wheel_record_integrity_verified": wheel_gate["wheel_record_integrity_verified"],
        "transitive_closure_proven": False,
        "audit_executor_authenticated": False,
        "declared_lock_origin_authenticated": False,
        "wheel_provider_authenticated": False,
        "vulnerability_service_live_queried": False,
        "license_distributions_requiring_review": license_gate["packages_review_pending"],
        "license_files_declared": license_gate["declared_license_files"],
        "license_files_integrity_checked": license_gate[
            "license_files_checked_against_wheel_record"],
        "spdx_identifiers_validated": False,
        "legal_license_review_completed": False,
        "third_party_licenses_verified": False,
        "packages_installed": False,
        "approved_for_install": False,
        "approved_for_production": False,
        "release_gate": "BLOCKED_PENDING_AUTHENTICATED_LOCK_ORIGIN_CLOSURE_CVE_LICENSE_AND_RUNTIME_TESTS",
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Coerência de evidências e hash de wheels, offline")
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[2])
    parser.add_argument("--lock", type=Path, required=True)
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("--metadata", type=Path, required=True)
    parser.add_argument("--wheelhouse", type=Path, required=True)
    args = parser.parse_args()
    try:
        meta = _json_seguro(_arquivo(args.metadata, 16_000))
        result = verificar_cadeia(
            _arquivo(args.root / "pyproject.toml", 80_000),
            _arquivo(args.lock, 300_000),
            _arquivo(args.report, 1_000_000),
            meta,
            args.wheelhouse,
        )
    except (ErroEvidencia, OSError) as exc:
        parser.exit(2, f"CADEIA_BLOQUEADA: {exc}\n")
    print(json.dumps(result, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
