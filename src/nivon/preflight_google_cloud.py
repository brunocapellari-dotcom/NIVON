"""Pré-voo não destrutivo Google Cloud para coletores NIVON.

Verifica recursos EXISTENTES e contrato de carga, sem criar dataset, fazer
upload, executar SQL ou assumir que aprovações manuais comprovam orçamento.
Rejeita bucket sem Public Access Prevention explícita e acesso uniforme.
"""
from __future__ import annotations

import argparse
import json
import re
from dataclasses import dataclass
from typing import Any

from .carga_bigquery_fontes import PROJECT, DATASET, COLS

BUCKET = re.compile(r"^[a-z0-9][a-z0-9._-]{1,61}[a-z0-9]$")
EXPECTED_SCHEMA = {field: ("JSON" if field == "campos" else "STRING") for field in COLS}


class ErroPreflightCloud(ValueError):
    pass


def verificar_configuracao(*, projeto: str, dataset: str, bucket: str) -> dict:
    """Checa apenas argumentos de identificação, não autentica ou consulta nuvem."""
    if (not isinstance(projeto,str) or not PROJECT.fullmatch(projeto) or
        not isinstance(dataset,str) or not DATASET.fullmatch(dataset) or
        not isinstance(bucket,str) or not BUCKET.fullmatch(bucket)):
        raise ErroPreflightCloud("projeto, dataset ou bucket inválidos")
    return {"projeto":projeto,"dataset":dataset,"bucket":bucket,
            "tabela":f"{projeto}.{dataset}.nivon_observacoes"}


def verificar_recursos(*, projeto: str, dataset: str, bucket: str,
                       cliente_storage=None, cliente_bigquery=None,
                       exigir_mesma_localizacao: bool=True) -> dict:
    """Read-only: consulta política de acesso, metadados e schema reais.

    A verificação é intencionalmente conservadora: se o bucket herda a
    prevenção de acesso público de uma organização mas não a define nele,
    bloquear até o operador comprovar ou configurar 'enforced'.
    """
    cfg=verificar_configuracao(projeto=projeto,dataset=dataset,bucket=bucket)
    if cliente_storage is None:
        try:
            from google.cloud import storage
        except ImportError as exc:
            raise RuntimeError("instalar extra gcp: google-cloud-storage") from exc
        cliente_storage=storage.Client(project=projeto)
    if cliente_bigquery is None:
        try:
            from google.cloud import bigquery
        except ImportError as exc:
            raise RuntimeError("instalar extra gcp: google-cloud-bigquery") from exc
        cliente_bigquery=bigquery.Client(project=projeto)
    if (getattr(cliente_storage,"project",projeto)!=projeto or
            getattr(cliente_bigquery,"project",projeto)!=projeto):
        raise ErroPreflightCloud("cliente ADC aponta para outro projeto")
    # get_bucket baixa metadados (inclusive IAM configuration), não escreve.
    objeto=cliente_storage.get_bucket(bucket)
    if objeto is None or getattr(objeto,"name",None)!=bucket:
        raise ErroPreflightCloud("bucket inexistente ou nome inesperado")
    iam=getattr(objeto,"iam_configuration",None)
    if iam is None:
        raise ErroPreflightCloud("configuração IAM do bucket indisponível")
    uniform=getattr(iam,"uniform_bucket_level_access_enabled",None)
    prevention=getattr(iam,"public_access_prevention",None)
    if uniform is not True or prevention!="enforced":
        raise ErroPreflightCloud("bucket não comprovadamente privado: exigir uniform access e PAP=enforced")
    if getattr(objeto,"location",None) is None:
        raise ErroPreflightCloud("bucket sem localização verificável")
    dset=cliente_bigquery.get_dataset(f"{projeto}.{dataset}")
    table=cliente_bigquery.get_table(cfg["tabela"])
    if (dset is None or getattr(dset,"location",None) is None or
            table is None or getattr(table,"table_type",None)!="TABLE"):
        raise ErroPreflightCloud("dataset, localização ou tabela física não verificados")
    if getattr(table,"project",projeto)!=projeto or getattr(table,"dataset_id",dataset)!=dataset:
        raise ErroPreflightCloud("tabela física fora do destino")
    bq_location=str(dset.location).upper()
    gcs_location=str(objeto.location).upper()
    if exigir_mesma_localizacao and bq_location!=gcs_location:
        raise ErroPreflightCloud("GCS e BigQuery em localizações diferentes: custo e residência requerem validação")
    schema=getattr(table,"schema",None)
    if not isinstance(schema,(tuple,list)):
        raise ErroPreflightCloud("schema BigQuery ausente")
    actual={}
    for col in schema:
        name=getattr(col,"name",None)
        if name in actual:
            raise ErroPreflightCloud("coluna repetida no schema")
        actual[name]=(str(getattr(col,"field_type","")).upper(),
                      str(getattr(col,"mode","NULLABLE")).upper())
    missing=[k for k in EXPECTED_SCHEMA if k not in actual]
    wrong=[k for k,t in EXPECTED_SCHEMA.items()
           if k in actual and (actual[k][0]!=t or actual[k][1] not in ("NULLABLE","REQUIRED"))]
    if missing or wrong:
        raise ErroPreflightCloud("BigQuery schema incompatível: faltantes="+
                                ",".join(missing)+" tipos="+",".join(wrong))
    # O DDL atual usa string 'referencia' e não tem partição. Não presumir.
    partition=getattr(table,"time_partitioning",None)
    return {
        "status":"PRONTO_PARA_SMOKE_CONTROLADO",
        "recursos_validados":True,
        "acesso_gcs":"PAP_ENFORCED_E_UNIFORM",
        "localizacao_bigquery":bq_location,
        "localizacao_gcs":gcs_location,
        "tabela":cfg["tabela"],
        "schema_colunas_validadas":len(EXPECTED_SCHEMA),
        "particionamento_confirmado":bool(partition),
        "aviso_particionamento":None if partition else (
            "Tabela sem time_partitioning; migrar com compatibilidade de referencia DATE em novo desenho"),
        "executou_upload":False,
        "executou_query":False,
        "verificou_limite_orcamentario":False,
        "go_live_confirmado":False,
    }


def main(argv: list[str] | None=None) -> int:
    p=argparse.ArgumentParser(description="Verificar GCS privado e BigQuery sem escrever")
    p.add_argument("--projeto",required=True)
    p.add_argument("--dataset",required=True)
    p.add_argument("--bucket",required=True)
    p.add_argument("--executar",action="store_true",help="ler metadados reais por ADC")
    args=p.parse_args(argv)
    try:
        if args.executar:
            result=verificar_recursos(projeto=args.projeto,dataset=args.dataset,bucket=args.bucket)
        else:
            result={"status":"APENAS_CONFIGURACAO_NAO_VERIFICADA",
                    **verificar_configuracao(projeto=args.projeto,dataset=args.dataset,bucket=args.bucket),
                    "cloud_consultado":False}
        print(json.dumps(result,ensure_ascii=False,indent=2))
        return 0
    except (ErroPreflightCloud,RuntimeError) as exc:
        print(json.dumps({"status":"BLOQUEADO","motivo":str(exc)},ensure_ascii=False))
        return 2


if __name__=="__main__":
    raise SystemExit(main())
