#!/usr/bin/env python3
"""NIVON: release readiness audit, strictly offline and read-only.

This checks technical presence and explicit approval flags, NOT GCP service
existence, successful live data retrieval, source licensing, or security of an
already deployed service. No external imports, network, secrets, or writes
except an optional new local JSON report requested by the operator.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]

ARTIFACTS = {
    "painel_interno": (
        "scripts/publicar_painel_interno.py",
        "src/nivon/painel_lancamento.py",
        ".github/workflows/nivon-go-live-interno.yml",
    ),
    "terminal_privado": (
        "src/nivon/terminal_web.py",
        "scripts/deploy_terminal_privado.sh",
        "infra/google_cloud/Dockerfile.terminal",
        ".github/workflows/nivon-terminal-go-live.yml",
    ),
    "maritimo_existente": (
        "src/nivon/maritimo_gcp_job.py",
        ".github/workflows/maritimo-gcp-primeiro-lote.yml",
    ),
}

def flag(env: dict[str, str], key: str) -> bool:
    return env.get(key) == "true"

def present(env: dict[str, str], key: str) -> bool:
    return bool(env.get(key, "").strip())

def check_configuration(env: dict[str, str]) -> dict[str, bool]:
    return {
        "google_cloud_project_esperado": env.get("NIVON_BQ_PROJECT") == "nivon-data",
        "dataset_esperado": env.get("NIVON_BQ_DATASET") == "nivon_raw",
        "bucket_esperado": env.get("NIVON_GCS_BUCKET") == "nivon-data-raw-2026",
        "oidc_provider_configurado": present(env, "NIVON_GCP_PROVIDER"),
        "oidc_service_account_configurada": present(env, "NIVON_GCP_SERVICE_ACCOUNT"),
        "custos_revisados": flag(env, "NIVON_GCP_COST_REVIEWED"),
        "publicacao_painel_interno_aprovada": flag(env, "NIVON_PAINEL_INTERNO_WRITE_APPROVED"),
        "terminal_deploy_aprovado": flag(env, "NIVON_GO_LIVE_DEPLOY_APPROVED"),
        "terminal_artifact_repo": present(env, "NIVON_TERMINAL_ARTIFACT_REPO"),
        "terminal_execution_identity": present(env, "NIVON_TERMINAL_EXECUTION_SA"),
        "maritimo_consulta_cota_aprovada": flag(env, "NIVON_ZERO_COST_BQ_APPROVED"),
        "maritimo_arquivo_raw_aprovado": flag(env, "NIVON_RAW_ARCHIVE_APPROVED"),
        "maritimo_cron_habilitado": env.get("NIVON_MARITIMO_GITHUB_SCHEDULE") == "enabled",
    }

def evaluate(root: Path = ROOT, env: dict[str, str] | None = None, *, now=None) -> dict:
    env = dict(os.environ if env is None else env)
    now = now or datetime.now(timezone.utc)
    files = {area: all((root / name).is_file() for name in names)
             for area, names in ARTIFACTS.items()}
    workflow_internal = root / ".github/workflows/nivon-go-live-interno.yml"
    workflow_maritime = root / ".github/workflows/maritimo-gcp-primeiro-lote.yml"
    workflow_terminal = root / ".github/workflows/nivon-terminal-go-live.yml"
    internal = workflow_internal.read_text(encoding="utf-8") if workflow_internal.exists() else ""
    maritime = workflow_maritime.read_text(encoding="utf-8") if workflow_maritime.exists() else ""
    terminal = workflow_terminal.read_text(encoding="utf-8") if workflow_terminal.exists() else ""
    policies = {
        "painel_somente_main": "github.ref == 'refs/heads/main'" in internal,
        "painel_pede_consentimento_para_escrita": (
            "vars.NIVON_PAINEL_INTERNO_WRITE_APPROVED == 'true'" in internal
            and "vars.NIVON_GCP_COST_REVIEWED == 'true'" in internal
            and "vars.NIVON_PAINEL_INTERNO_AGENDADO == 'true'" in internal
            and "inputs.publicar == true" in internal
        ),
        "maritimo_cron_somente_ativacao_afirmativa": (
            "vars.NIVON_MARITIMO_GITHUB_SCHEDULE == 'enabled'" in maritime
            and "vars.NIVON_ZERO_COST_BQ_APPROVED == 'true'" in maritime
            and "vars.NIVON_RAW_ARCHIVE_APPROVED == 'true'" in maritime
        ),
        "terminal_somente_main_manual": (
            "github.ref == 'refs/heads/main'" in terminal
            and "github.event_name == 'workflow_dispatch'" in terminal
            and "inputs.confirmar_deploy == true" in terminal
            and "vars.NIVON_GO_LIVE_DEPLOY_APPROVED == 'true'" in terminal
            and "vars.NIVON_GCP_COST_REVIEWED == 'true'" in terminal
        ),
    }
    config = check_configuration(env)
    basics = all(config[k] for k in (
        "google_cloud_project_esperado", "dataset_esperado",
        "bucket_esperado", "oidc_provider_configurado",
        "oidc_service_account_configurada",
    ))
    internal_gate = (files["painel_interno"] and policies["painel_somente_main"]
                     and policies["painel_pede_consentimento_para_escrita"])
    terminal_gate = (files["terminal_privado"]
                     and policies["terminal_somente_main_manual"])
    maritime_gate = (files["maritimo_existente"]
                     and policies["maritimo_cron_somente_ativacao_afirmativa"])
    lanes = {
        "painel_interno_gcs": {
            "etapa": "GO_LIVE_INTERNO_SHADOW",
            "codigo_preparado": internal_gate,
            "preflight_configuracao_completo": (
                internal_gate and basics and config["custos_revisados"]
                and config["publicacao_painel_interno_aprovada"]
            ),
            "acao_pendente": "Confirmar WIF/IAM, disponibilidade dos dados e custos; depois usar workflow_dispatch publicar=true em main.",
            "dados_reais_verificados_nesta_auditoria": False,
            "publicacao_executada": False,
        },
        "terminal_privado_cloud_run": {
            "etapa": "TERMINAL_READONLY_PRIVADO",
            "codigo_preparado": terminal_gate,
            "preflight_configuracao_completo": (
                terminal_gate and basics and config["custos_revisados"]
                and config["terminal_deploy_aprovado"]
                and config["terminal_artifact_repo"]
                and config["terminal_execution_identity"]
            ),
            "acao_pendente": "Verificar recursos existentes e IAM; autorizar custos e executar workflow_dispatch confirmar_deploy=true em main.",
            "dados_reais_verificados_nesta_auditoria": False,
            "deploy_executado": False,
        },
        "maritimo_piloto_imbituba_portwatch": {
            "etapa": "INGESTAO_CONTROLADA_INFORMADO_ESTIMADO",
            "codigo_preparado": maritime_gate,
            "preflight_configuracao_completo": (
                maritime_gate and basics
                and config["maritimo_consulta_cota_aprovada"]
                and config["maritimo_arquivo_raw_aprovado"]
            ),
            "cron_aprovado_nesta_auditoria": False,
            "acao_pendente": "Comprovar licença, qualidade e custos das fontes existentes; confirmar WIF e agendar apenas quando aprovada a ativação.",
            "carga_real_comprovada_nesta_auditoria": False,
        },
        "maritimo_pdf_sem_duv": {
            "etapa": "DESENVOLVIMENTO_ISOLADO",
            "codigo_preparado": False,
            "preflight_configuracao_completo": False,
            "motivo": "Stack PDF/AIS em PRs draft divergentes de main, sem direitos oficiais ou DUV comprovado.",
            "publicacao_permitida": False,
        },
    }
    return {
        "produto": "NIVON",
        "gerado_em_utc": now.astimezone(timezone.utc).isoformat(),
        "tipo": "AUDITORIA_ESTÁTICA_OFFLINE_SEM_CLOUD",
        "estado": "CONFIGURACAO_GATES_NAO_DEPLOY",
        "configuracao": config,
        "arquivos_presentes": files,
        "politicas": policies,
        "trilhas": lanes,
        "violacoes_de_politica": [key for key, ok in policies.items() if not ok],
        "escritas_cloud": 0,
        "consultas_bigquery": 0,
        "deploys": 0,
        "fontes_homologadas_por_este_comando": 0,
        "liberacao_publica": False,
    }

def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--json", type=Path, help="Novo arquivo JSON de auditoria; nunca sobrescrever")
    parser.add_argument("--strict-policy", action="store_true",
                        help="Retornar erro quando uma política de release falhar")
    args = parser.parse_args(argv)
    report = evaluate()
    output = json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    if args.json:
        with args.json.open("x", encoding="utf-8") as dest:
            dest.write(output)
    else:
        sys.stdout.write(output)
    return 3 if args.strict_policy and report["violacoes_de_politica"] else 0

if __name__ == "__main__":
    raise SystemExit(main())
