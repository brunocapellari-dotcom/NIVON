"""NIVON: verifica destino Cloud sem criar recursos de forma silenciosa.

Bootstrap explicitamente autorizado cria SOMENTE a tabela particionada em
dataset pré-existente. Nenhuma credencial é armazenada.
"""
from __future__ import annotations

import argparse
import json

from .arquivo_raw_gcs import _validar_bucket
from .carga_bigquery_fontes import PROJECT, DATASET, COLS, ErroCargaBigQuery

CANONICOS = (
    ("data_referencia","DATE"),
    ("data_publicacao","TIMESTAMP"),
    ("data_coleta","TIMESTAMP"),
)
STAGE = (
    ("dataset_id","STRING"),("identidade","STRING"),("fingerprint","STRING"),
    ("referencia","STRING"),("competencia","STRING"),("publicacao","STRING"),
    ("coletado_em","STRING"),("unidade","STRING"),("valor","STRING"),
    ("campos","JSON"),("snapshot_id","STRING"),("natureza","STRING"),
)


def validar_config(*, projeto, dataset, bucket):
    if not isinstance(projeto,str) or not PROJECT.fullmatch(projeto):
        raise ErroCargaBigQuery("ID projeto GCP invalido")
    if not isinstance(dataset,str) or not DATASET.fullmatch(dataset):
        raise ErroCargaBigQuery("dataset GCP invalido")
    _validar_bucket(bucket)
    return {"projeto":projeto,"dataset":dataset,
        "bucket":bucket,"tabela":f"{projeto}.{dataset}.nivon_observacoes"}


def verificar_nuvem(*, projeto, dataset, bucket, criar_tabela=False,
                     client_bq=None, client_storage=None):
    args=validar_config(projeto=projeto,dataset=dataset,bucket=bucket)
    try:
        from google.cloud import bigquery, storage
        from google.api_core.exceptions import NotFound
    except ImportError as exc:
        raise RuntimeError("extras NIVON[gcp] ausentes") from exc
    bq=client_bq if client_bq is not None else bigquery.Client(project=projeto)
    gcs=client_storage if client_storage is not None else storage.Client(project=projeto)
    # Preflight somente: projeto, dataset e bucket devem ter sido provisionados.
    bq.get_dataset(f"{projeto}.{dataset}")
    if not gcs.bucket(bucket).exists(client=gcs):
        raise ErroCargaBigQuery("bucket GCS nao existente/sem permissao")
    try:
        tabela=bq.get_table(args["tabela"])
        criado=False
    except NotFound:
        if criar_tabela is not True:
            raise ErroCargaBigQuery("tabela BigQuery ausente; bootstrap explicito necessario")
        schema=[bigquery.SchemaField(nome,tipo,mode="REQUIRED" if
                 nome in {"dataset_id","identidade","fingerprint",
                          "referencia","coletado_em","data_referencia","data_coleta",
                          "snapshot_id","natureza"} else "NULLABLE")
                for nome,tipo in STAGE+CANONICOS]
        tabela=bigquery.Table(args["tabela"],schema=schema)
        tabela.time_partitioning=bigquery.TimePartitioning(
            type_=bigquery.TimePartitioningType.DAY,field="data_referencia")
        tabela.clustering_fields=["dataset_id","identidade","fingerprint"]
        tabela.description="NIVON: observacoes versionadas com origem RAW no GCS, nenhuma publicacao automatica"
        tabela=bq.create_table(tabela,exists_ok=True)
        criado=True
    schema={col.name:col.field_type.upper() for col in tabela.schema}
    campos_necessarios=dict(STAGE+CANONICOS)
    if any(schema.get(nome)!=tipo for nome,tipo in campos_necessarios.items()):
        raise ErroCargaBigQuery("schema BigQuery divergente")
    partition=tabela.time_partitioning
    if partition is None or partition.field!="data_referencia":
        raise ErroCargaBigQuery("tabela BigQuery sem particionamento")
    return {**args,"dataset_existe":True,"bucket_existe":True,
        "tabela_criada":criado,"tabela_validada":True,
        "auth":"OIDC_ADC","coleta_executada":False}


def main(argv=None):
    p=argparse.ArgumentParser(description="Pré-voo BigQuery/GCS NIVON")
    p.add_argument("--projeto",required=True)
    p.add_argument("--dataset",required=True)
    p.add_argument("--bucket",required=True)
    p.add_argument("--criar-tabela",action="store_true")
    x=p.parse_args(argv)
    ret=verificar_nuvem(projeto=x.projeto,dataset=x.dataset,bucket=x.bucket,
                       criar_tabela=x.criar_tabela)
    print(json.dumps(ret,ensure_ascii=False,indent=2))
    return 0

if __name__=="__main__":
    raise SystemExit(main())
