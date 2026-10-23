"""Batch operational NIVON: collect a verified public dataset -> GCS -> BigQuery.

Fail closed on grant, runtime, cost and identity. For IMEA only RAW quarantine
is sent to GCS, never into the canonical BigQuery observations table.
"""
from __future__ import annotations

import argparse
import json
import os
from datetime import date, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from nivon.conectores_publicos_gcp import coletar, preparar_consulta
from nivon.coletor_imea_origem import coletar_imea
from nivon.persistencia_google_cloud import planejar_envio, executar_envio

ALLOWED = frozenset({"BCB_PTAX", "IBGE_PAM", "IMEA_WORKBOOK"})
SOURCE_OPS = frozenset({"COLETA","ARMAZENAMENTO","PROCESSAMENTO"})


def executar_lote(*, fonte: str, base: str | Path,
                 project_id: str, dataset_id: str, bucket: str,
                 executar: bool = False, aprovacao: bool = False,
                 evidencia: str = "", origem_imea: str | None = None,
                 inicio: str | None = None, fim: str | None = None,
                 municipio_ibge: str | None = None, ano: int | None = None,
                 codigo_produto: str | None = None,
                 codigo_variavel: str | None = None,
                 abridor=None, storage_client=None, bq_loader=None,
                 instante=None) -> dict:
    if fonte not in ALLOWED:
        raise ValueError("fonte fora dos conectores implementados")
    if executar is not True:
        return {"status":"PLANEJADO_SEM_REDE",
                "fonte":fonte,"passos":["HTTP_origem","parser_NIVON","RAW_SQLite",
                                      "GCS","BigQuery_se_normalizado"],
                "cloud_executado":False}
    if aprovacao is not True or len(evidencia.strip())<10:
        raise PermissionError("operacao Google Cloud/direitos ainda nao aprovados")
    base=Path(base)
    if fonte=="IMEA_WORKBOOK":
        if not origem_imea:
            raise ValueError("IMEA sem URL oficial publicada e validada")
        coleta=coletar_imea(
            url=origem_imea,base=base,autorizacoes=SOURCE_OPS,
            evidencia=evidencia,executar=True,abridor=abridor,instante=instante)
        cloud_bigquery=False
    else:
        if fonte=="BCB_PTAX":
            hoje=datetime.now(ZoneInfo("America/Sao_Paulo")).date()
            fim=fim or hoje.isoformat()
            inicio=inicio or (date.fromisoformat(fim)-timedelta(days=14)).isoformat()
            plano=preparar_consulta(fonte,moeda="USD",inicio=inicio,fim=fim)
        else:
            if any(x is None for x in (municipio_ibge,ano,codigo_produto,codigo_variavel)):
                raise ValueError("IBGE requer municipio, ano, codigo produto e variavel")
            plano=preparar_consulta(
                fonte,municipio_ibge=municipio_ibge,ano=ano,
                codigo_produto_c81=codigo_produto,codigo_variavel=codigo_variavel)
        coleta=coletar(
            fonte=fonte,plano=plano,banco=base/"fontes_reais.sqlite",
            raw_dir=base/"raw",autorizacoes=SOURCE_OPS,
            executar=True,abridor=abridor,instante=instante)
        cloud_bigquery=True
    cloud=executar_envio(
        base=base,bucket=bucket,project_id=project_id,dataset_id=dataset_id,
        bigquery=cloud_bigquery,executar=True,
        autorizacoes=SOURCE_OPS,evidencia=evidencia,
        storage_client=storage_client,bq_loader=bq_loader)
    return {
        "fonte":fonte,"coleta":coleta,"gcp":cloud,
        "cloud_executado":cloud["gcs_executado"],
        "bigquery_executado":cloud["bq_executado"],
        "status":"GCS_QUARENTENA" if fonte=="IMEA_WORKBOOK" else "GCS_BIGQUERY",
    }


def main(argv=None):
    p=argparse.ArgumentParser(description="NIVON fonte especifica -> Google Cloud duravel")
    p.add_argument("--fonte",required=True,choices=sorted(ALLOWED))
    p.add_argument("--base",default="data/nivon")
    p.add_argument("--executar",action="store_true")
    p.add_argument("--inicio");p.add_argument("--fim")
    p.add_argument("--municipio-ibge");p.add_argument("--ano",type=int)
    p.add_argument("--codigo-produto");p.add_argument("--codigo-variavel")
    args=p.parse_args(argv)
    execute=args.executar
    # Users must explicitly configure approved operations and a budget gate.
    approved=(os.getenv("NIVON_GCP_OPERACIONAL_APROVADO")=="true"
              and os.getenv("NIVON_GCP_DIREITOS_DADOS")=="true"
              and os.getenv("NIVON_ZERO_COST_BQ_APPROVED")=="true")
    result=executar_lote(
        fonte=args.fonte,base=args.base,
        project_id=os.getenv("NIVON_BQ_PROJECT",""),
        dataset_id=os.getenv("NIVON_BQ_DATASET",""),
        bucket=os.getenv("NIVON_GCS_BUCKET",""),
        executar=execute,aprovacao=approved,
        evidencia=os.getenv("NIVON_GCP_RIGHTS_EVIDENCE",""),
        origem_imea=os.getenv("NIVON_IMEA_XLSX_URL") or None,
        inicio=args.inicio,fim=args.fim,
        municipio_ibge=args.municipio_ibge,ano=args.ano,
        codigo_produto=args.codigo_produto,codigo_variavel=args.codigo_variavel)
    print(json.dumps(result,ensure_ascii=False,indent=2))
    return 0


if __name__=="__main__":
    raise SystemExit(main())
