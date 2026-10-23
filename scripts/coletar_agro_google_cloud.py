"""Coleta real CEPEA/IMEA/CONAB -> ledger NIVON -> RAW GCS -> BQ homologado.

A coleta e o envio só ocorrem com switches explícitos e autorização operacional;
um comando não converte staging IMEA/CONAB em dado físico canônico.
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

from nivon.agro_origem_gcp import FONTES, executar as coletar
from nivon.arquivo_raw_gcs import arquivar_gcs
from nivon.ingestao_fontes_reais import exportar_jsonl
from nivon.lote_cloud_recuperavel import arquivar_stage
from nivon.carga_bigquery_fontes import executar_carga


def executar_lote(*, fonte, base, executar=False, enviar_gcs=False,
                  homologar_cepea=False, bigquery=False, projeto=None,
                  dataset=None, bucket=None, cliente=None):
    if fonte not in FONTES:
        raise ValueError("fonte não homologada")
    if not executar:
        return {"fonte":fonte,"estado":"PLANO_SEM_REDE",
                "fluxo":["COLETA_OFICIAL","LEDGER_RAW",
                         "GCS_SE_APROVADO","BIGQUERY_SE_REFERENCIA_HOMOLOGADA"],
                "executado":False}
    if os.getenv("NIVON_AGRO_FONTE_AUTORIZADA")!="true":
        raise PermissionError("fonte CEPEA/IMEA/CONAB sem gate de direitos")
    if homologar_cepea and fonte not in ("CEPEA_SOJA","CEPEA_MILHO"):
        raise PermissionError("somente CEPEA tem data de referência conferida")
    if bigquery and not (enviar_gcs and homologar_cepea):
        raise PermissionError("BigQuery requer CEPEA homologado e GCS confirmado")
    if (enviar_gcs or bigquery) and (
        os.getenv("NIVON_RAW_ARCHIVE_APPROVED")!="true"
        or os.getenv("NIVON_ZERO_COST_BQ_APPROVED")!="true"
        or not (projeto and dataset and bucket)):
        raise PermissionError("Cloud IAM/custos/destino ainda não aprovados")
    if homologar_cepea and os.getenv("NIVON_CEPEA_HOMOLOGACAO_APROVADA")!="true":
        raise PermissionError("CEPEA sem gate explícito de homologação/licença")
    raiz=Path(base)
    if raiz.is_symlink():
        raise ValueError("caminho base via symlink")
    # Evita repetir HTTP no modo de replay; o módulo original é idempotente.
    saida=coletar(fonte=fonte,base=raiz,cliente=cliente,
                  homologacao_referencia=homologar_cepea)
    ds=saida["dataset"]
    if not enviar_gcs:
        return {"coleta":saida,"estado":"PERSISTIDO_LOCALMENTE",
                "gcs_executado":False,"bigquery_executado":False}
    arquivo=arquivar_gcs(
        banco=raiz/"fontes_reais.sqlite",raw_dir=raiz/"raw",bucket=bucket,
        fonte_dataset=ds,executar=True)
    result={"coleta":saida,"gcs":arquivo,"gcs_executado":True,
            "bigquery_executado":False,
            "estado":"GCS_RAW_QUARENTENA" if not bigquery else "GCS_STAGE_ARQUIVADO"}
    if bigquery:
        stage=raiz/(ds.lower()+"_normalized.jsonl")
        exportado=exportar_jsonl(
            banco=raiz/"fontes_reais.sqlite",destino=stage,dataset_id=ds)
        if exportado["observacoes"]<1:
            raise ValueError("fonte homologada sem observações")
        recibo=arquivar_stage(
            banco=raiz/"fontes_reais.sqlite",arquivo_jsonl=stage,
            bucket=bucket,projeto=projeto,dataset=dataset,executar=True)
        result["recibo"]=recibo
        carga=executar_carga(
            arquivo=stage,project_id=projeto,dataset_id=dataset,executar=True)
        if carga.get("executado") is not True:
            raise RuntimeError("MERGE BigQuery não confirmado")
        result["bigquery_executado"]=True
        result["estado"]="GCS_BIGQUERY_HOMOLOGADO_SEM_PUBLICACAO_EXTERNA"
    return result


def main(argv=None):
    p=argparse.ArgumentParser(description="NIVON agro -> RAW GCS/BigQuery")
    p.add_argument("--fonte",required=True,choices=FONTES)
    p.add_argument("--base",default="data/nivon/agro")
    p.add_argument("--executar",action="store_true")
    p.add_argument("--gcs",action="store_true")
    p.add_argument("--bigquery",action="store_true")
    p.add_argument("--homologar-cepea",action="store_true")
    args=p.parse_args(argv)
    resultado=executar_lote(
        fonte=args.fonte,base=args.base,executar=args.executar,
        enviar_gcs=args.gcs,bigquery=args.bigquery,
        homologar_cepea=args.homologar_cepea,
        projeto=os.getenv("NIVON_BQ_PROJECT"),
        dataset=os.getenv("NIVON_BQ_DATASET"),
        bucket=os.getenv("NIVON_GCS_BUCKET"))
    print(json.dumps(resultado,ensure_ascii=False,indent=2,default=str))
    return 0


if __name__=="__main__":
    raise SystemExit(main())
