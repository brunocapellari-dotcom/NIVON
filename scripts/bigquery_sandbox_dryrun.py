#!/usr/bin/env python3
"""NIVON: provar acesso BigQuery por dry-run, sem criar recursos nem gastar.

Usa auditoria autenticada read-only; somente prossegue se billing confirmado
DISABLED e API BigQuery confirmada ENABLED. Nenhuma query real e executada.
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path
from typing import Any, Callable

import audit_gcp_readonly


def preflight(
    project: str,
    report: dict[str, Any],
    runner: Callable[..., subprocess.CompletedProcess[str]] = subprocess.run,
) -> dict[str, Any]:
    """Falha fechada. O retorno nao divulga identificadores ou erros do CLI."""
    status = {
        "project_id": project,
        "audit_verified": report.get("project_verified_by_api") is True,
        "billing_status": report.get("billing_status", "UNKNOWN_NOT_VERIFIED"),
        "bigquery_api_verified_enabled": False,
        "dry_run_validated": False,
        "dry_run_only": True,
        "resources_created": False,
        "paid_spending_authorized": False,
        "migration_performed": False,
    }
    if report.get("project_id") != project or not status["audit_verified"]:
        status["next_gate"] = "PROJECT_VERIFICATION_REQUIRED"
        return status
    if status["billing_status"] != "DISABLED":
        status["next_gate"] = "BILLING_VERIFICATION_OR_REVIEW_REQUIRED"
        return status
    apis = report.get("apis_of_interest")
    if not isinstance(apis, dict) or apis.get("bigquery.googleapis.com") is not True:
        status["next_gate"] = "BIGQUERY_API_ENABLEMENT_NEEDS_SEPARATE_REVIEW"
        return status
    status["bigquery_api_verified_enabled"] = True

    command = [
        "bq", "--project_id=" + project, "--location=us-central1",
        "query", "--use_legacy_sql=false", "--dry_run",
        "--maximum_bytes_billed=1073741824",
        "SELECT 'NIVON' AS plataforma, 1 AS valido",
    ]
    try:
        result = runner(command, capture_output=True, text=True, check=False, timeout=30)
        status["dry_run_validated"] = result.returncode == 0
    except (OSError, subprocess.TimeoutExpired):
        status["dry_run_validated"] = False
    status["next_gate"] = (
        "SANDBOX_DRY_RUN_OK_NO_DATA_STORED" if status["dry_run_validated"]
        else "BIGQUERY_DRY_RUN_NOT_AVAILABLE"
    )
    return status


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Smoke test sem custos: SOMENTE BigQuery dry run.")
    parser.add_argument("--check", action="store_true")
    parser.add_argument("--project", default="nivon-data")
    args = parser.parse_args(argv)
    if not args.check:
        parser.print_help()
        return 2
    try:
        config = json.loads(
            (Path(__file__).resolve().parents[1] / "config/gcp_data_platform.v1.json").read_text()
        )
    except (OSError, ValueError):
        print("CONFIG_INVALID", file=sys.stderr)
        return 2
    if args.project != config.get("gcp_project_id") or config.get("billing", {}).get("paid_use_approved") is True:
        print("GCP_GUARD_BLOCK", file=sys.stderr)
        return 2
    report = audit_gcp_readonly.audit(args.project)
    status = preflight(args.project, report)
    print(json.dumps(status, indent=2, ensure_ascii=False, sort_keys=True))
    return 0 if status["dry_run_validated"] else 3


if __name__ == "__main__":
    raise SystemExit(main())
