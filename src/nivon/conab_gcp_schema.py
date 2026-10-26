"""Contrato de tabela BigQuery de quarentena CONAB na infraestrutura NIVON.

Não cria projetos/datasets, só UMA tabela no dataset preexistente sob
aprovação explícita. "Verificar" faz leitura de metadados. Clientes
autenticados por ADC/WIF, nenhum secret armazenado.
"""
from __future__ import annotations

import argparse
import json
import re

from .agro_bigquery_loader import _TIPOS, _TABELA


class ErroSchemaConab(ValueError):pass


def verificar_ou_criar(*,projeto:str,dataset:str,aplicar:bool=False,
                      schema_aprovado:bool=False,custos_autorizados:bool=False,
                      cliente=None,sdk=None,not_found=None)->dict:
    if not isinstance(projeto,str) or not re.fullmatch(r'[a-z][a-z0-9-]{4,61}[a-z0-9]',projeto):
        raise ErroSchemaConab('projeto GCP invalido')
    if not isinstance(dataset,str) or not re.fullmatch(r'[a-zA-Z_][a-zA-Z0-9_]{0,120}',dataset):
        raise ErroSchemaConab('dataset BQ invalido')
    if aplicar and (schema_aprovado is not True or custos_autorizados is not True):
        raise PermissionError('criar tabela exige aprovacao de schema e custos')
    if cliente is None or sdk is None:
        from google.cloud import bigquery
        if cliente is None:cliente=bigquery.Client(project=projeto)
        if sdk is None:sdk=bigquery
    if not_found is None:
        from google.api_core.exceptions import NotFound
        not_found=NotFound
    root=cliente.get_dataset(f'{projeto}.{dataset}')
    if str(root.location or '').lower()!='southamerica-east1':
        raise ErroSchemaConab('dataset fora da regiao NIVON')
    ref=f'{projeto}.{dataset}.{_TABELA}'
    try:
        table=cliente.get_table(ref)
    except not_found:
        if not aplicar:
            return {'status':'TABELA_STAGE_AUSENTE_SEM_CRIACAO','tabela':ref,
                    'criada':False}
        schema=[sdk.SchemaField(name,kind,mode='NULLABLE') for name,kind in _TIPOS.items()]
        novo=sdk.Table(ref,schema=schema)
        novo.time_partitioning=sdk.TimePartitioning(
            type_=sdk.TimePartitioningType.DAY,field='coletado_utc')
        novo.clustering_fields=['source_id','dataset_id','produto','source_sha256']
        novo.description='NIVON Agro fontes: QUARENTENA NAO PUBLICAVEL'
        table=cliente.create_table(novo,exists_ok=False)
        criado=True
    else:
        criado=False
    tipos={x.name:x.field_type.upper() for x in table.schema}
    if tipos!=_TIPOS:
        raise ErroSchemaConab('schema de tabela existente diverge do contrato')
    if str(table.location or '').lower()!='southamerica-east1':
        raise ErroSchemaConab('tabela BQ fora da regiao NIVON')
    part=getattr(table,'time_partitioning',None)
    if part is None or part.field!='coletado_utc':
        raise ErroSchemaConab('tabela deve particionar por coletado_utc')
    return {'status':'SCHEMA_GCP_STAGE_VALIDADO','tabela':ref,
            'colunas':len(_TIPOS),'criada':criado,'publicavel':False}


def main():
    p=argparse.ArgumentParser(description='NIVON CONAB: validar/criar tabela BQ ja no dataset autorizado')
    p.add_argument('--projeto',required=True)
    p.add_argument('--dataset',required=True)
    p.add_argument('--aplicar',action='store_true')
    p.add_argument('--schema-aprovado',action='store_true')
    p.add_argument('--custos-autorizados',action='store_true')
    a=p.parse_args()
    resp=verificar_ou_criar(projeto=a.projeto,dataset=a.dataset,aplicar=a.aplicar,
          schema_aprovado=a.schema_aprovado,custos_autorizados=a.custos_autorizados)
    print(json.dumps(resp,sort_keys=True,ensure_ascii=False))
    return 0 if resp['status']=='SCHEMA_GCP_STAGE_VALIDADO' else 2


if __name__=='__main__':
    raise SystemExit(main())
