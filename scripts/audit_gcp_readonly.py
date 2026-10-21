#!/usr/bin/env python3
"""Auditoria SOMENTE LEITURA do Google Cloud do NIVON.

Comandos: projects describe, billing projects describe, services list --enabled
e projects get-iam-policy. A saida nao contem emails, billingAccountName,
projectNumber, tokens ou principals IAM. O script nunca habilita servicos.
Requer Cloud Shell ou gcloud CLI autenticado. Sem bibliotecas externas.
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path
from typing import Any, Callable, Sequence

ROOT = Path(__file__).resolve().parents[1]
CONFIG_PATH = ROOT / "config" / "gcp_data_platform.v1.json"
PROJECT_PATTERN = re.compile(r"^[a-z][a-z0-9-]{4,28}[a-z0-9]$")
INTEREST_APIS = (
    "bigquery.googleapis.com",
    "storage.googleapis.com",
    "run.googleapis.com",
    "cloudscheduler.googleapis.com",
    "cloudbilling.googleapis.com",
)


def gcloud_json(args: Sequence[str]) -> Any | None:
    """Executa uma consulta fechada; erros e stdout bruto nao sao divulgados."""
    allowed = (
        ("projects", "describe"),
        ("billing", "projects", "describe"),
        ("services", "list"),
        ("projects", "get-iam-policy"),
    )
    if not any(tuple(args[: len(prefix)]) == prefix for prefix in allowed):
        raise ValueError("Comando fora da lista de consultas permitidas")
    try:
        result = subprocess.run(
            ["gcloud", *args],
            capture_output=True,
            text=True,
            check=False,
            timeout=30,
        )
        if result.returncode != 0:
            return None
        return json.loads(result.stdout)
    except (OSError, subprocess.TimeoutExpired, ValueError):
        return None


def _safe_services(value: Any) -> list[str] | None:
    if not isinstance(value, list):
        return None
    output: set[str] = set()
    for item in value:
        if not isinstance(item, dict):
            continue
        config = item.get("config")
        api = config.get("name") if isinstance(config, dict) else None
        if not api and isinstance(item.get("name"), str):
            api = item["name"].split("/")[-1]
        if isinstance(api, str) and re.fullmatch(r"[a-z0-9.-]+\\.googleapis\\.com", api):
            output.add(api)
    return sorted(output)


def audit(project_id: str, fetch: Callable[[Sequence[str]], Any | None] = gcloud_json) -> dict[str, Any]:
    """Injeta fetch nas provas offline; sem mutacao, inclusive com billing ativo."""
    project = fetch(("projects", "describe", project_id, "--format=json"))
    confirmed = isinstance(project, dict) and project.get("projectId") == project_id
    lifecycle = project.get("lifecycleState") if confirmed else None

    billing = fetch(("billing", "projects", "describe", project_id, "--format=json")) if confirmed else None
    status = "UNKNOWN_NOT_VERIFIED"
    if isinstance(billing, dict):
        if billing.get("billingEnabled") is True:
            status = "ENABLED"
        elif billing.get("billingEnabled") is False:
            status = "DISABLED"

    services = fetch(("services", "list", "--enabled", "--project=" + project_id, "--format=json")) if confirmed else None
    enabled = _safe_services(services)
    iam = fetch(("projects", "get-iam-policy", project_id, "--format=json")) if confirmed else None
    bindings = iam.get("bindings") if isinstance(iam, dict) else None
    iam_count = len(bindings) if isinstance(bindings, list) else None

    return {
        "audit_schema_version": "1.0.0",
        "project_id": project_id,
        "project_verified_by_api": bool(confirmed),
        "project_lifecycle": lifecycle if lifecycle in ("ACTIVE", "DELETE_REQUESTED", "DELETE_IN_PROGRESS") else "UNKNOWN",
        "billing_status": status,
        "billing_account_identifier_included": False,
        "api_inventory_verified": enabled is not None,
        "enabled_apis": enabled,
        "apis_of_interest": (
            {api: api in enabled for api in INTEREST_APIS} if enabled is not None else None
        ),
        "iam_audit_verified": iam_count is not None,
        "iam_binding_count": iam_count,
        "iam_principal_identifiers_included": False,
        "resources_deployed_verified": False,
        "deploy_allowed": False,
        "paid_spending_authorized": False,
        "legacy_neon_ptax_preserved": True,
        "next_gate": (
            "CONFIRM_PROJECT_ACCESS" if not confirmed else
            "CONFIRM_BILLING_ACCESS" if status == "UNKNOWN_NOT_VERIFIED" else
            "BILLING_ACTIVE_REVIEW_REQUIRED" if status == "ENABLED" else
            "EVALUATE_SANDBOX_TEST_NO_DURABLE_DATA"
        ),
    }


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Inventario seguro e redigido do projeto GCP do NIVON; sem escrita."
    )
    parser.add_argument("--check", action="store_true", help="Autoriza apenas consultas de leitura.")
    parser.add_argument("--project", default="nivon-data", help="ID do projeto ja criado.")
    args = parser.parse_args(argv)
    if not args.check:
        parser.print_help()
        return 2
    if not PROJECT_PATTERN.fullmatch(args.project):
        parser.error("ID de projeto GCP invalido")
    try:
        config = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        print("Configuracao ausente ou invalida; operacao interrompida.", file=sys.stderr)
        return 2
    if args.project != config.get("gcp_project_id"):
        print("ID diferente da configuracao versionada; operacao interrompida.", file=sys.stderr)
        return 2
    result = audit(args.project)
    print(json.dumps(result, ensure_ascii=False, sort_keys=True, indent=2))
    # 0 quer dizer que a auditoria tem billing confirmado, NAO autoriza deploy.
    return 0 if result["project_verified_by_api"] and result["billing_status"] != "UNKNOWN_NOT_VERIFIED" else 3


if __name__ == "__main__":
    raise SystemExit(main())
