"""Diagnóstico do terminal: metadados somente, sem SQL, build, deploy ou IAM write."""
from __future__ import annotations

import argparse
import json
import os
import re
import subprocess

from .terminal_web import PROJETO, DATASET

REGIAO = "southamerica-east1"
GATES = ("NIVON_GCP_COST_REVIEWED", "NIVON_GO_LIVE_DEPLOY_APPROVED",
         "NIVON_TERMINAL_IAM_REVIEWED")


class FalhaMetadados(Exception):
    """Código público; nunca transportar stdout/stderr de ferramentas externas."""


def _gcloud(*args):
    try:
        proc = subprocess.run(["gcloud", *args, "--format=json", "--quiet"],
                              capture_output=True, text=True, timeout=30, check=False)
    except FileNotFoundError:
        raise FalhaMetadados("GCLOUD_AUSENTE") from None
    except (OSError, subprocess.TimeoutExpired):
        raise FalhaMetadados("METADADOS_INDISPONIVEIS") from None
    if proc.returncode:
        # Não adivinhar se 403 é recurso ausente. Nenhum erro bruto é publicado.
        raise FalhaMetadados("ACESSO_OU_RECURSO_INDISPONIVEL")
    try:
        return json.loads(proc.stdout)
    except (ValueError, TypeError):
        raise FalhaMetadados("RESPOSTA_INVALIDA") from None


def coletar_metadados(repo, sa):
    """Mesmas verificações de recursos do deploy existente; não chama seu script."""
    accounts = _gcloud("auth", "list", "--filter=status:ACTIVE")
    if not isinstance(accounts, list) or not accounts:
        raise FalhaMetadados("CREDENCIAL_GCLOUD_AUSENTE")
    from google.cloud import bigquery
    bq = bigquery.Client(project=PROJETO, location=REGIAO)
    dataset = bq.get_dataset(f"{PROJETO}.{DATASET}")
    view = bq.get_table(f"{PROJETO}.{DATASET}.vw_antt_ferrovia_od_atual")
    project_arg = f"--project={PROJETO}"
    region_arg = f"--region={REGIAO}"
    return {
        "dataset": {"location": dataset.location},
        "view": {"table_type": view.table_type},
        "artifact": _gcloud("artifacts", "repositories", "describe", repo,
                             project_arg, f"--location={REGIAO}"),
        "service_account": _gcloud("iam", "service-accounts", "describe", sa,
                                    project_arg),
        "billing": _gcloud("billing", "projects", "describe", PROJETO),
        "project_policy": _gcloud("projects", "get-iam-policy", PROJETO),
        "service": _gcloud("run", "services", "describe", "nivon-terminal",
                            project_arg, region_arg),
        "service_policy": _gcloud("run", "services", "get-iam-policy",
                                   "nivon-terminal", project_arg, region_arg),
    }


def _private(policy):
    if not isinstance(policy, dict) or not isinstance(policy.get("bindings"), list):
        return False
    # Includes inherited public grants, not only service-level run.invoker.
    return all(isinstance(b, dict) and isinstance(b.get("members"), list)
               and not {"allUsers", "allAuthenticatedUsers"}.intersection(b["members"])
               for b in policy["bindings"])


def diagnosticar(env=None, *, executar=False, coletor=coletar_metadados):
    env = os.environ if env is None else env
    checks = {}
    def check(name, ok):
        checks[name] = "OK" if ok is True else "BLOQUEADO"
    repo = env.get("NIVON_TERMINAL_ARTIFACT_REPO", "")
    sa = env.get("NIVON_TERMINAL_EXECUTION_SA", "")
    check("projeto", env.get("NIVON_PROJETO") == PROJETO)
    check("dataset", env.get("NIVON_DATASET") == DATASET)
    check("artifact_config", bool(re.fullmatch(r"[a-z][a-z0-9-]{1,62}", repo)))
    check("execution_sa_config", bool(re.fullmatch(
        r"[a-z][a-z0-9-]{4,28}[a-z0-9]@nivon-data\.iam\.gserviceaccount\.com", sa)))
    for name in GATES:
        check(name, env.get(name) == "true")
    report = {"schema_version": 1, "projeto": PROJETO, "dataset": DATASET,
              "regiao": REGIAO, "checks": checks, "ready_for_deploy": False,
              "metadados_consultados": False, "consultas_sql": 0, "gravacoes": 0,
              "iam_efetivo_testado": False, "go_live": False}
    if not all(v == "OK" for v in checks.values()):
        report["estado"] = "CONFIGURACAO_PENDENTE"
        return report
    if executar is not True:
        report["estado"] = "PLANO_SEM_REDE"
        return report
    try:
        data = coletor(repo, sa)
        check("regiao_dataset", str(data["dataset"]["location"]).lower() == REGIAO)
        check("view_bq", data["view"]["table_type"] == "VIEW")
        artifact = data["artifact"]
        check("artifact_docker", artifact.get("format") == "DOCKER" and
              artifact.get("name") == f"projects/{PROJETO}/locations/{REGIAO}/repositories/{repo}")
        account = data["service_account"]
        check("execution_sa", account.get("email") == sa and not account.get("disabled", False))
        check("billing_habilitado", data["billing"].get("billingEnabled") is True)
        check("iam_projeto_privado", _private(data["project_policy"]))
        check("iam_servico_privado", _private(data["service_policy"]))
        service = data["service"]
        spec = service.get("spec", {})
        annotations = service.get("metadata", {}).get("annotations", {})
        check("servico_identificado", service.get("metadata", {}).get("labels", {}).get("nivon-component") == "terminal")
        check("invoker_iam_habilitado", annotations.get("run.googleapis.com/invoker-iam-disabled", "false") == "false")
        check("execution_sa_servico", spec.get("template", {}).get("spec", {}).get("serviceAccountName") == sa)
        report["metadados_consultados"] = True
    except FalhaMetadados as exc:
        # Only codes generated by this module, never arbitrary exception text.
        allowed = {"GCLOUD_AUSENTE", "METADADOS_INDISPONIVEIS", "CREDENCIAL_GCLOUD_AUSENTE",
                   "ACESSO_OU_RECURSO_INDISPONIVEL", "RESPOSTA_INVALIDA"}
        report["erro"] = str(exc) if str(exc) in allowed else "METADADOS_INDISPONIVEIS"
    except Exception:
        report["erro"] = "METADADOS_INDISPONIVEIS"
    report["ready_for_deploy"] = (report["metadados_consultados"] and
                                  all(v == "OK" for v in checks.values()))
    report["estado"] = "PREFLIGHT_OK" if report["ready_for_deploy"] else "METADADOS_OU_RECURSOS_PENDENTES"
    return report


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--executar", action="store_true", help="Consultar somente metadados GCP após gates")
    args = parser.parse_args(argv)
    report = diagnosticar(executar=args.executar)
    print(json.dumps(report, ensure_ascii=False, sort_keys=True))
    return 0 if report["ready_for_deploy"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
