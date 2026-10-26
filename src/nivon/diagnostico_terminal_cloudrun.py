"""Diagnóstico do terminal privado NIVON — exclusivamente metadados GCP.

Nenhum comando mutante, consulta SQL, build, deploy, IAM ou API enable.
Apenas a main autenticada por WIF deve executar contra o Cloud.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import subprocess

PROJECT="nivon-data"
DATASET="nivon_raw"
REGION="southamerica-east1"
SERVICES=("run.googleapis.com","cloudbuild.googleapis.com","artifactregistry.googleapis.com")
REPO_PATTERN=re.compile(r"^[a-z][a-z0-9-]{1,62}$")
SA_PATTERN=re.compile(r"^[a-z][a-z0-9-]{4,28}[a-z0-9]@nivon-data\.iam\.gserviceaccount\.com$")
ALLOWED_STATUS=frozenset({"CONFIRMADO","AUSENTE","SEM_PERMISSAO",
                          "NAO_CONFIGURADO","DIVERGENTE","INDETERMINADO"})

class ErroDiagnostico(ValueError):
    pass


def _classificar(exc):
    msg=str(exc).lower()
    if "403" in msg or "permission" in msg or "unauthorized" in msg:
        return "SEM_PERMISSAO"
    if "404" in msg or "not found" in msg or "not_found" in msg:
        return "AUSENTE"
    return "INDETERMINADO"


def _comando(args, *, runner=subprocess.run):
    assert args and args[0]=="gcloud"
    # Opcional injetar runner testável. Nunca usar shell=True ou imprimir stderr.
    try:
        result=runner(args,capture_output=True,text=True,timeout=24,check=False)
    except (OSError,subprocess.TimeoutExpired):
        return "INDETERMINADO",None
    if result.returncode:
        return _classificar(result.stderr),None
    try:
        value=json.loads(result.stdout)
        if not isinstance(value,dict):raise ValueError("metadados nao objetos")
        return "CONFIRMADO",value
    except (ValueError,TypeError):
        return "INDETERMINADO",None


def _bigquery(reader=None):
    if reader is None:
        from google.cloud import bigquery
        client=bigquery.Client(project=PROJECT,location=REGION)
        reader=client
    result={}
    try:
        d=reader.get_dataset(f"{PROJECT}.{DATASET}")
        result["dataset"]="CONFIRMADO" if str(d.location).lower()==REGION else "DIVERGENTE"
    except Exception as exc:
        result["dataset"]=_classificar(exc)
    try:
        table=reader.get_table(f"{PROJECT}.{DATASET}.vw_antt_ferrovia_od_atual")
        result["view"]="CONFIRMADO" if table.table_type=="VIEW" else "DIVERGENTE"
    except Exception as exc:
        result["view"]=_classificar(exc)
    return result


def diagnosticar(*,repositoriodeimagens="",contaexecucao="",runner=subprocess.run,
                reader=None):
    if not isinstance(repositoriodeimagens,str) or not isinstance(contaexecucao,str):
        raise ErroDiagnostico("configuracao deve ser string")
    if repositoriodeimagens and not REPO_PATTERN.fullmatch(repositoriodeimagens):
        raise ErroDiagnostico("repositório de imagens invalido")
    if contaexecucao and not SA_PATTERN.fullmatch(contaexecucao):
        raise ErroDiagnostico("conta de execução invalida")
    statuses={}
    for name in SERVICES:
        status,data=_comando(["gcloud","services","describe",name,
                    "--project="+PROJECT,"--format=json"],runner=runner)
        if status=="CONFIRMADO":
            status="CONFIRMADO" if data.get("state")=="ENABLED" else "AUSENTE"
        statuses[name]=status
    if repositoriodeimagens:
        status,data=_comando(["gcloud","artifacts","repositories","describe",
                 repositoriodeimagens,"--location="+REGION,"--project="+PROJECT,
                 "--format=json"],runner=runner)
        if status=="CONFIRMADO":
            status="CONFIRMADO" if data.get("format")=="DOCKER" else "DIVERGENTE"
    else:
        status="NAO_CONFIGURADO"
    statuses["artifact_repository"]=status
    if contaexecucao:
        status,data=_comando(["gcloud","iam","service-accounts","describe",
                       contaexecucao,"--project="+PROJECT,"--format=json"],runner=runner)
        if status=="CONFIRMADO":
            status="CONFIRMADO" if (data.get("email")==contaexecucao
                 and data.get("disabled") is not True) else "DIVERGENTE"
    else:
        status="NAO_CONFIGURADO"
    statuses["execution_service_account"]=status
    table_states=_bigquery(reader=reader)
    statuses.update({"bigquery_"+k:v for k,v in table_states.items()})
    # Ausente pode ser válido: script de deploy cria um serviço novo. Isso não
    # comprova permissão de criar o serviço nem permissão de build.
    st,service=_comando(["gcloud","run","services","describe","nivon-terminal",
                         "--region="+REGION,"--project="+PROJECT,
                         "--format=json"],runner=runner)
    statuses["terminal_cloudrun_existente"]=st
    if st=="CONFIRMADO":
        labels=(service.get("metadata") or {}).get("labels") or {}
        if labels.get("nivon-component")!="terminal":
            statuses["terminal_cloudrun_existente"]="DIVERGENTE"
        else:
            iam,policy=_comando(["gcloud","run","services","get-iam-policy","nivon-terminal",
                         "--region="+REGION,"--project="+PROJECT,
                         "--format=json"],runner=runner)
            if iam=="CONFIRMADO":
                public=any(x.get("role")=="roles/run.invoker"
                  and set(x.get("members") or ())&{"allUsers","allAuthenticatedUsers"}
                  for x in (policy.get("bindings") or ()))
                statuses["terminal_iam_privado"]="DIVERGENTE" if public else "CONFIRMADO"
            else:
                statuses["terminal_iam_privado"]=iam
    else:
        statuses["terminal_iam_privado"]="NAO_CONFIGURADO" if st=="AUSENTE" else st
    required=[*SERVICES,"artifact_repository","execution_service_account",
              "bigquery_dataset","bigquery_view"]
    meta_ok=all(statuses.get(n)=="CONFIRMADO" for n in required)
    safe_existing=(statuses["terminal_cloudrun_existente"]=="AUSENTE"
        or (statuses["terminal_cloudrun_existente"]=="CONFIRMADO"
            and statuses["terminal_iam_privado"]=="CONFIRMADO"))
    return {
       "projeto":PROJECT,"dataset":DATASET,"regiao":REGION,
       "componentes":statuses,"metadados_basicos_confirmados":meta_ok and safe_existing,
       "autorizacao_de_deploy_verificada":False,"permissao_de_escrita_verificada":False,
       "orcamento_verificado":False,"sql_executado":False,
       "alteracoes_cloud":0,"go_live_homologado":False,
       "proxima_acao":"VALIDAR_IAM_E_ORCAMENTO_PARA_DEPLOY" if meta_ok and safe_existing
         else "CORRIGIR_RECURSOS_OU_PERMISSOES_INDICADOS"
    }


def main(argv=None):
    p=argparse.ArgumentParser(description="Auditoria sem escrita do terminal Cloud Run")
    p.add_argument("--repo",default=os.environ.get("NIVON_TERMINAL_ARTIFACT_REPO",""))
    p.add_argument("--sa",default=os.environ.get("NIVON_TERMINAL_EXECUTION_SA",""))
    a=p.parse_args(argv)
    print(json.dumps(diagnosticar(repositoriodeimagens=a.repo,contaexecucao=a.sa),
                     ensure_ascii=False,indent=2,sort_keys=True))
    return 0


if __name__=="__main__":
    raise SystemExit(main())
