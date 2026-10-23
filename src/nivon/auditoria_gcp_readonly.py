"""Auditoria NIVON de metadados Google Cloud com permissão estritamente de leitura.

A consulta não lista objetos, não varre dados, não executa SQL, não cria
recursos e não verifica permissão de escrita. Uso recomendado: GitHub OIDC.
"""
from __future__ import annotations

import argparse
import json
from dataclasses import dataclass

from .preflight_gcp_fontes import validar_config

ESQUEMA_CANONICO = {
    "dataset_id": "STRING",
    "identidade": "STRING",
    "fingerprint": "STRING",
    "data_referencia": "DATE",
    "data_coleta": "TIMESTAMP",
    "data_publicacao": "TIMESTAMP",
    "snapshot_id": "STRING",
    "natureza": "STRING",
}
ESQUEMA_AGRO = {
    "data_coleta": "TIMESTAMP",
    "data_referencia": "DATE",
    "snapshot_id": "STRING",
}


class ErroAuditoriaCloud(ValueError):
    pass


def _regiao(valor):
    if not isinstance(valor,str) or not valor.strip():
        raise ErroAuditoriaCloud("regiao cloud ausente")
    return valor.strip().lower()


def _analisar_tabela(nome, tabela, esperados, particao):
    if tabela is None:
        return {"tabela":nome,"existe":False,"schema_conforme":False,
                "particao_conforme":False}
    schema={str(f.name):str(f.field_type).upper() for f in tabela.schema}
    incorretos=sorted(k for k, tipo in esperados.items() if schema.get(k)!=tipo)
    temporal=getattr(tabela,"time_partitioning",None)
    tem_particao=temporal is not None and getattr(temporal,"field",None)==particao
    return {"tabela":nome,"existe":True,"schema_conforme":not incorretos,
            "colunas_pendentes_ou_incorretas":incorretos,
            "particao_conforme":tem_particao,
            "campo_particao_esperado":particao}


def avaliar_metadados(*, projeto, dataset, bucket, local_dataset,
                      local_bucket, tabela_canonica, tabela_agro):
    info=validar_config(projeto=projeto,dataset=dataset,bucket=bucket)
    regiao_bq=_regiao(local_dataset)
    regiao_gcs=_regiao(local_bucket)
    esperado="southamerica-east1"
    tabelas=[
        _analisar_tabela("nivon_observacoes",tabela_canonica,
            ESQUEMA_CANONICO,"data_referencia"),
        _analisar_tabela("agro_publicacoes_staging",tabela_agro,
            ESQUEMA_AGRO,"data_coleta"),
    ]
    return {
        "projeto":info["projeto"],"dataset":info["dataset"],"bucket":info["bucket"],
        "regiao_bigquery":regiao_bq,"regiao_gcs":regiao_gcs,
        "regiao_conforme":regiao_bq==esperado and regiao_gcs==esperado,
        "tabelas":tabelas,
        "acesso_metadados_confirmado":True,
        "pronto_para_operacao":False,
        "motivo":("Esta auditoria não testa direitos de coleta, IAM de escrita, "
                  "custo, gravação/recuperação ou execução ponta a ponta."),
        "acoes_cloud_realizadas":["bigquery.datasets.get",
                                  "storage.buckets.get",
                                  "bigquery.tables.get (se permitido)"],
        "gravacoes":0,"consultas_sql":0,
    }


def auditar(*,projeto,dataset,bucket,executar=False,
            cliente_bigquery=None,cliente_storage=None):
    conf=validar_config(projeto=projeto,dataset=dataset,bucket=bucket)
    if executar is not True:
        return {**conf,"executado":False,"tipo":"PLANO_SEM_REDE"}
    try:
        from google.cloud import bigquery, storage
        from google.api_core.exceptions import NotFound
    except ImportError as exc:
        raise RuntimeError("instale nivon[gcp] e autentique com WIF/ADC") from exc
    bq=cliente_bigquery if cliente_bigquery is not None else bigquery.Client(project=projeto)
    gcs=cliente_storage if cliente_storage is not None else storage.Client(project=projeto)
    ds=bq.get_dataset(f"{projeto}.{dataset}")
    bk=gcs.get_bucket(bucket)
    def tabela(nome):
        try:
            return bq.get_table(f"{projeto}.{dataset}.{nome}")
        except NotFound:
            return None
    retorno=avaliar_metadados(
        projeto=projeto,dataset=dataset,bucket=bucket,
        local_dataset=ds.location, local_bucket=bk.location,
        tabela_canonica=tabela("nivon_observacoes"),
        tabela_agro=tabela("agro_publicacoes_staging"))
    return {**retorno,"executado":True,"autenticacao":"ADC_WIF_LEITURA"}


def main(argv=None):
    p=argparse.ArgumentParser(description="Auditar infraestrutura NIVON sem escrita na Cloud")
    p.add_argument("--projeto",required=True)
    p.add_argument("--dataset",required=True)
    p.add_argument("--bucket",required=True)
    p.add_argument("--executar",action="store_true")
    a=p.parse_args(argv)
    result=auditar(projeto=a.projeto,dataset=a.dataset,bucket=a.bucket,executar=a.executar)
    print(json.dumps(result,ensure_ascii=False,indent=2))
    if result.get("executado") and not result["regiao_conforme"]:
        return 2
    return 0


if __name__=="__main__":
    raise SystemExit(main())
