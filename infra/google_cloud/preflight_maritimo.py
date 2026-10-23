"""Preflight SOMENTE LEITURA da infraestrutura Google Cloud para NIVON.

Uso: python infra/google_cloud/preflight_maritimo.py --regiao REGION
Detecta projeto do ambiente GCP atual, sem criar/modificar recursos nem
exibir credenciais ou conta autenticada. Emite evidencias de verificacao.
"""
from __future__ import annotations
import argparse
import json
import os
import re
import subprocess
from pathlib import Path

SERVICOS = (
    "bigquery.googleapis.com",
    "storage.googleapis.com",
    "run.googleapis.com",
    "cloudscheduler.googleapis.com",
    "cloudbuild.googleapis.com",
    "artifactregistry.googleapis.com",
)
PROJETO_RE=r"[a-z][a-z0-9-]{4,61}[a-z0-9]"
REGIAO_RE=r"[a-z]+(?:-[a-z0-9]+)+[0-9]"


def executar_comando(args, *, runner=subprocess.run):
    """Nenhum argumento passa pelo shell; stdout limitado e sem segredos."""
    if not args or args[0] not in ("gcloud","bq"):
        raise ValueError("comando fora de gcloud/bq")
    if any(flag in args for flag in ("create","delete","deploy","update","set-iam-policy","enable")):
        raise ValueError("preflight deve ser estritamente read-only")
    try:
        result=runner(args,capture_output=True,text=True,timeout=35,check=False)
    except (FileNotFoundError,subprocess.TimeoutExpired,PermissionError):
        return {"estado":"NAO_VERIFICADO","codigo":"CLI_INDISPONIVEL"}
    if result.returncode==0:
        try:
            return {"estado":"OK","dados":json.loads(result.stdout)}
        except (ValueError,TypeError):
            return {"estado":"OK","dados":result.stdout.strip()[:180]}
    err=(result.stderr or "").lower()
    if ("not found" in err or "404" in err) and not any(
        x in err for x in ("permission", "forbidden", "unauthorized","access denied")
    ):
        return {"estado":"AUSENTE_CONFIRMADO","codigo":"404"}
    return {"estado":"NAO_VERIFICADO","codigo":"SEM_PERMISSAO_OU_FALHA"}


def auditoria(*, projeto=None, regiao, dataset="nivon_maritimo",
             bucket=None, job="nivon-maritimo", agendamento="nivon-maritimo-6h",
             runner=subprocess.run):
    if not re.fullmatch(REGIAO_RE,regiao):
        raise ValueError("regiao GCP invalida")
    if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]{0,255}",dataset):
        raise ValueError("dataset invalido")
    if not re.fullmatch(r"[a-z][a-z0-9-]{1,61}[a-z0-9]",job):
        raise ValueError("job invalido")
    if projeto is None:
        projeto=os.getenv("GOOGLE_CLOUD_PROJECT")
    if not projeto:
        current=executar_comando(["gcloud","config","get-value","project"],runner=runner)
        projeto=current.get("dados") if current["estado"]=="OK" else None
    if not isinstance(projeto,str) or not re.fullmatch(PROJETO_RE,projeto):
        raise ValueError("projeto GCP nao identificado; informe --projeto")
    if bucket is not None and not re.fullmatch(r"[a-z0-9][a-z0-9._-]{2,61}[a-z0-9]",bucket):
        raise ValueError("bucket invalido")
    opts=["--project="+projeto]
    r={
        "projeto":projeto,"regiao":regiao,"dataset":dataset,
        "modo":"SOMENTE_LEITURA",
        "projeto_info":executar_comando(["gcloud","projects","describe",projeto,"--format=json"],runner=runner),
        "apis":executar_comando(["gcloud","services","list","--enabled",*opts,"--format=json"],runner=runner),
        "bigquery_dataset":executar_comando(["bq","--project_id="+projeto,"show",
            "--format=prettyjson",projeto+":"+dataset],runner=runner),
        "cloud_run_job":executar_comando(["gcloud","run","jobs","describe",job,
            "--region="+regiao,*opts,"--format=json"],runner=runner),
        "scheduler":executar_comando(["gcloud","scheduler","jobs","describe",agendamento,
            "--location="+regiao,*opts,"--format=json"],runner=runner),
    }
    if bucket:
        r["bucket"]=executar_comando(["gcloud","storage","buckets","describe",
                                      "gs://"+bucket,"--format=json"],runner=runner)
    else:
        r["bucket"]={"estado":"NAO_VERIFICADO","codigo":"BUCKET_NAO_INFORMADO"}
    apis=r["apis"]
    if apis["estado"]=="OK" and isinstance(apis.get("dados"),list):
        available={a.get("config",{}).get("name","").split("/")[-1] for a in apis["dados"] if isinstance(a,dict)}
        r["servicos_necessarios"]={service:service in available for service in SERVICOS}
    else:
        r["servicos_necessarios"]={service:None for service in SERVICOS}
    # Sem claims de implantacao quando nao ha API autenticada.
    r["apto_para_implantacao"]=(
        r["projeto_info"]["estado"]=="OK" and
        r["bigquery_dataset"]["estado"]=="OK" and
        r["bucket"]["estado"]=="OK" and
        all(v is True for v in r["servicos_necessarios"].values())
    )
    # Expor apenas metadados validados para evitar vazamento de IAM e conta.
    for key in ("projeto_info","apis","bigquery_dataset","cloud_run_job","scheduler","bucket"):
        r[key].pop("dados",None)
    return r


def main(argv=None):
    parser=argparse.ArgumentParser(description="Inventario read-only GCP NIVON")
    parser.add_argument("--projeto")
    parser.add_argument("--regiao",required=True)
    parser.add_argument("--dataset",default="nivon_maritimo")
    parser.add_argument("--bucket")
    parser.add_argument("--saida",type=Path)
    args=parser.parse_args(argv)
    report=auditoria(projeto=args.projeto,regiao=args.regiao,
                    dataset=args.dataset,bucket=args.bucket)
    json_str=json.dumps(report,indent=2,ensure_ascii=False,sort_keys=True)
    if args.saida:
        with args.saida.open("x",encoding="utf-8") as f:
            f.write(json_str)
    print(json_str)

if __name__=="__main__":
    main()
