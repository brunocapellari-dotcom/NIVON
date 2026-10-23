"""Coleta real CEPEA/IMEA/CONAB -> ledger NIVON -> RAW GCS -> BQ homologado.

A coleta e o envio só ocorrem com switches explícitos e autorização operacional;
um comando não converte staging IMEA/CONAB em dado físico canônico.
"""
from __future__ import annotations

import argparse
import json
import os
import sqlite3
from pathlib import Path

from nivon.agro_origem_gcp import FONTES, executar as coletar
from nivon.arquivo_raw_gcs import arquivar_gcs
from nivon.ingestao_fontes_reais import exportar_jsonl
from nivon.lote_cloud_recuperavel import arquivar_stage
from nivon.carga_bigquery_fontes import executar_carga


def _tem_observacoes_deste_lote(banco, snapshots):
    # O registro permanece ligado ao primeiro snapshot que introduziu
    # aquele fingerprint; novos RAWs sem delta não geram stage vazio.
    banco=Path(banco)
    if banco.is_symlink() or not banco.is_file():
        raise ValueError("ledger ausente")
    uri=f"file:{banco.resolve().as_posix()}?mode=ro"
    with sqlite3.connect(uri,uri=True) as db:
        sql="SELECT COUNT(*) FROM observacoes WHERE snapshot_id IN (" + (
            ",".join("?" for _ in snapshots)) + ")"
        return db.execute(sql,snapshots).fetchone()[0] > 0


def executar_lote(*, fonte, base, executar=False, enviar_gcs=False,
                  homologar_cepea=False, bigquery=False, staging_bigquery=False, projeto=None,
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
        raise PermissionError("BigQuery canônico requer CEPEA homologado e GCS")
    if staging_bigquery and (not enviar_gcs or bigquery or homologar_cepea
                             or fonte not in ("IMEA","CONAB")):
        raise PermissionError("staging BQ exige IMEA/CONAB em GCS; sem promoção")
    if (enviar_gcs or bigquery or staging_bigquery) and (
        os.getenv("NIVON_RAW_ARCHIVE_APPROVED")!="true"
        or os.getenv("NIVON_ZERO_COST_BQ_APPROVED")!="true"
        or not (projeto and dataset and bucket)):
        raise PermissionError("Cloud IAM/custos/destino ainda não aprovados")
    if staging_bigquery and os.getenv("NIVON_AGRO_STAGING_BIGQUERY_APPROVED")!="true":
        raise PermissionError("tabela staging BigQuery sem gate de gravação")
    if homologar_cepea and os.getenv("NIVON_CEPEA_HOMOLOGACAO_APROVADA")!="true":
        raise PermissionError("CEPEA sem gate explícito de homologação/licença")
    raiz=Path(base)
    if raiz.is_symlink():
        raise ValueError("caminho base via symlink")
    # Evita repetir HTTP no modo de replay; o módulo original é idempotente.
    saida=coletar(fonte=fonte,base=raiz,cliente=cliente,
                  homologacao_referencia=homologar_cepea)
    ds=saida["dataset"]
    if fonte.startswith("CEPEA_"):
        selecionados=[saida["snapshot_id"]]
    elif fonte=="IMEA":
        selecionados=[item["snapshot_id"] for item in saida["cadeias"]]
    else:
        selecionados=[item["snapshot_id"] for item in saida["edicoes"]]
    if not selecionados or len(set(selecionados))!=len(selecionados):
        raise ValueError("snapshots da coleta ausentes ou duplicados")
    if not enviar_gcs:
        return {"coleta":saida,"estado":"PERSISTIDO_LOCALMENTE",
                "gcs_executado":False,"bigquery_executado":False}
    arquivo=arquivar_gcs(
        banco=raiz/"fontes_reais.sqlite",raw_dir=raiz/"raw",bucket=bucket,
        fonte_dataset=ds,snapshot_ids=selecionados,executar=True)
    result={"coleta":saida,"gcs":arquivo,"gcs_executado":True,
            "bigquery_executado":False,
            "estado":"GCS_RAW_QUARENTENA" if not bigquery else "GCS_STAGE_ARQUIVADO"}
    if not _tem_observacoes_deste_lote(
            raiz/"fontes_reais.sqlite",selecionados):
        result["estado"]="GCS_RAW_SEM_DELTA_ANALITICO"
        return result
    if staging_bigquery:
        from nivon.agro_staging_bigquery import (
            exportar_quarentena, arquivar_stage_quarentena, carregar_stage)
        stage=raiz/(ds.lower()+"_staging.jsonl")
        exportado=exportar_quarentena(
            banco=raiz/"fontes_reais.sqlite",destino=stage,
            fonte_dataset=ds,snapshot_ids=selecionados)
        recibo=arquivar_stage_quarentena(
            arquivo=stage,bucket=bucket,project_id=projeto)
        result["staging_recibo_gcs"]=recibo
        carga=carregar_stage(
            arquivo=stage,fonte_dataset=ds,project_id=projeto,
            dataset_id=dataset,executar=True)
        result["staging_bigquery"]=carga
        result["estado"]="BIGQUERY_STAGING_NAO_CANONICO"
        result["bigquery_executado"]=True
    if bigquery:
        stage=raiz/(ds.lower()+"_normalized.jsonl")
        exportado=exportar_jsonl(
            banco=raiz/"fontes_reais.sqlite",destino=stage,
            dataset_id=ds,snapshot_ids=selecionados)
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
    p.add_argument("--staging-bigquery",action="store_true")
    p.add_argument("--homologar-cepea",action="store_true")
    args=p.parse_args(argv)
    resultado=executar_lote(
        fonte=args.fonte,base=args.base,executar=args.executar,
        enviar_gcs=args.gcs,bigquery=args.bigquery,
        staging_bigquery=args.staging_bigquery,
        homologar_cepea=args.homologar_cepea,
        projeto=os.getenv("NIVON_BQ_PROJECT"),
        dataset=os.getenv("NIVON_BQ_DATASET"),
        bucket=os.getenv("NIVON_GCS_BUCKET"))
    print(json.dumps(resultado,ensure_ascii=False,indent=2,default=str))
    return 0


if __name__=="__main__":
    raise SystemExit(main())
