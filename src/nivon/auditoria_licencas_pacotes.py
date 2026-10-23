"""Resumo de evidências de licenças em wheelhouse, sem aprovação jurídica.

Exige a checagem anterior de wheel, RECORD e cabeçalhos. Declarações SPDX,
arquivos presentes e seus hashes não substituem licença válida ou auditoria.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from .auditoria_evidencias_pacotes import ErroEvidencia, _arquivo
from .auditoria_wheelhouse import verificar


def inventariar_licencas(wheel_summary: dict) -> dict:
    if (not isinstance(wheel_summary, dict) or
            wheel_summary.get("wheel_record_integrity_verified") is not True):
        raise ErroEvidencia("integridade de wheelhouse/RECORD não foi atestada")
    wheels = wheel_summary.get("verified_wheels")
    if (not isinstance(wheels, list) or not wheels or
            len(wheels) != wheel_summary.get("wheel_count")):
        raise ErroEvidencia("inventário de wheels incompleto")
    results = []
    files_count = 0
    metadata_moderno = 0
    for entry in wheels:
        if not isinstance(entry, dict) or entry.get("record_integrity_verified") is not True:
            raise ErroEvidencia("wheel sem RECORD verificado")
        evidence = entry.get("license_evidence")
        if not isinstance(evidence, dict) or evidence.get("licenses_approved") is not False:
            raise ErroEvidencia("evidência de licença ausente ou indevidamente aprovada")
        if evidence.get("license_content_legally_reviewed") is not False:
            raise ErroEvidencia("revisão jurídica indevidamente presumida")
        files = evidence.get("license_files")
        if not isinstance(files, list) or len(files) != evidence.get("license_file_count"):
            raise ErroEvidencia("número de arquivos de licença inconsistente")
        status = evidence.get("license_metadata_status")
        if status not in (
            "LEGACY_METADATA_MANUAL_REVIEW", "SPDX_EXPRESSION_DECLARED_UNVERIFIED",
            "SPDX_EXPRESSION_ABSENT_MANUAL_REVIEW",
        ):
            raise ErroEvidencia("status de licenciamento desconhecido")
        files_count += len(files)
        metadata_moderno += status != "LEGACY_METADATA_MANUAL_REVIEW"
        results.append({
            "distribution": entry["distribution"],
            "version": entry["version"],
            "wheel_sha256": entry["verified_sha256"],
            "metadata_version": evidence["metadata_version"],
            "license_expression_declared": evidence["license_expression_declared"],
            "status": status,
            "license_files": files,
            "legal_review_required": True,
        })
    return {
        "project": "NIVON",
        "analysis_type": "OFFLINE_LICENSE_DECLARATION_AND_FILE_HASH_INVENTORY",
        "packages_review_pending": len(results),
        "packages_modern_metadata": metadata_moderno,
        "declared_license_files": files_count,
        "distributions": results,
        "license_files_checked_against_wheel_record": True,
        "spdx_identifiers_validated_against_spdx_list": False,
        "license_authenticity_verified": False,
        "actual_license_compatibility_verified": False,
        "legal_review_completed": False,
        "third_party_packages_installed": False,
        "approved_for_install": False,
        "approved_for_production": False,
        "release_gate": "BLOCKED_PENDING_LICENSE_LEGAL_REVIEW_ORIGIN_LOCK_CVE_RUNTIME",
    }


def auditar(wheelhouse: Path, lock_text: str) -> dict:
    return inventariar_licencas(verificar(wheelhouse, lock_text))


def main() -> int:
    parser = argparse.ArgumentParser(description="Inventário offline de licenças de wheels")
    parser.add_argument("--wheelhouse", type=Path, required=True)
    parser.add_argument("--lock", type=Path, required=True)
    args = parser.parse_args()
    try:
        result = auditar(args.wheelhouse, _arquivo(args.lock, 300_000))
    except (ErroEvidencia, OSError) as exc:
        parser.exit(2, f"LICENCAS_BLOQUEADAS: {exc}\n")
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
