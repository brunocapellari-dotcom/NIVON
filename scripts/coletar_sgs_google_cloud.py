"""BCB Selic diaria SGS11 -> ledger compartilhado -> GCS + BigQuery."""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

from nivon.conectores_publicos_gcp import coletar_selic_diaria
from nivon.persistencia_google_cloud import executar_envio

OPERACOES=frozenset({"COLETA","ARMAZENAMENTO","PROCESSAMENTO"})


def executar_sgs(*,base,project_id,dataset_id,bucket,autorizacoes=frozenset(),
                 evidencia="",executar=False,abridor=None,storage_client=None,
                 bq_loader=None,instante=None):
    if executar is not True or not OPERACOES<=set(autorizacoes):
        raise PermissionError("BCB SGS requer coleta, armazenamento e processamento aprovados")
    if not isinstance(evidencia,str) or len(evidencia.strip())<10:
        raise PermissionError("evidência de operação ausente")
    path=Path(base)
    coleta=coletar_selic_diaria(banco=path/"fontes_reais.sqlite",raw_dir=path/"raw",
                executar=True,autorizacoes=autorizacoes,abridor=abridor,instante=instante)
    enviado=executar_envio(base=path,bucket=bucket,project_id=project_id,
             dataset_id=dataset_id,bigquery=True,executar=True,
             fonte_dataset="BCB_SGS_TAXA_SELIC_DIARIA",
             autorizacoes=autorizacoes,evidencia=evidencia,
             storage_client=storage_client,bq_loader=bq_loader)
    return {"fonte":"BCB_SGS_TAXA_SELIC_DIARIA",
            "coleta":coleta,"nuvem":enviado,
            "cloud_executado":enviado["gcs_executado"],
            "bigquery_executado":enviado["bq_executado"],
            "publicacao_automatica":False}


def main(argv=None):
    p=argparse.ArgumentParser(description="BCB SGS11 -> GCS/BQ autenticado")
    p.add_argument("--base",default="data/nivon/cloud_sgs")
    p.add_argument("--executar",action="store_true")
    args=p.parse_args(argv)
    if not args.executar:
        r={"modo":"PLANO_SEM_REDE","coleta":False,
           "fonte":"BCB_SGS_TAXA_SELIC_DIARIA",
           "pipeline":"HTTPS BCB->ledger RAW->GCS privado->BigQuery existente"}
    else:
        if not (os.getenv("NIVON_GCP_OPERACIONAL_APROVADO")=="true"
                and os.getenv("NIVON_ZERO_COST_BQ_APPROVED")=="true"
                and os.getenv("NIVON_FONTE_BCB_SGS_TAXA_SELIC_DIARIA_ATIVA")=="true"):
            raise PermissionError("BCB SGS GCP não aprovado")
        r=executar_sgs(
            base=args.base,project_id=os.environ["NIVON_BQ_PROJECT"],
            dataset_id=os.environ["NIVON_BQ_DATASET"],
            bucket=os.environ["NIVON_GCS_BUCKET"],
            autorizacoes=OPERACOES,
            evidencia=os.getenv("NIVON_GCP_RIGHTS_EVIDENCE",""),executar=True)
    print(json.dumps(r,ensure_ascii=False,indent=2))
    return 0


if __name__=="__main__":
    raise SystemExit(main())
