"""Carregamento BigQuery somente sob execução e autorização explícitas.

Recebe JSONL privado da quarentena Agro NIVON e escreve no dataset de
STAGING ja existente. Não cria projeto, dataset, tabela, recursos, cron ou
billing. Job-id determinístico reduz recargas, mas não substitui MERGE nem
verificação de integridade da tabela de destino.
"""
from __future__ import annotations

from hashlib import sha256
import argparse
import json
import os
from pathlib import Path
import re
import stat

from .agro_bigquery_stage import _FIELDS


class ErroUploadAgro(ValueError):
    pass


_ID=re.compile(r'^[a-zA-Z][a-zA-Z0-9_-]{4,90}$')
_TABELA='agro_fonte_stage'
_TIPOS={**{k:'STRING' for k in _FIELDS},'coletado_utc':'TIMESTAMP','data_coleta':'TIMESTAMP'}
_MAX_BYTES=100_000_000
_MAX_LINES=100_000


def validar_lote(arquivo:str|Path)->dict:
    """Audita formato e acesso local. NÃO conecta a nuvem nem a credenciais."""
    path=Path(arquivo)
    if not path.is_file() or path.is_symlink() or path.suffix!='.jsonl':
        raise ErroUploadAgro('arquivo JSONL privado existente requerido')
    if os.name=='posix':
        if stat.S_IMODE(path.stat().st_mode)&0o077:
            raise ErroUploadAgro('arquivo JSONL nao privado 0600')
        if stat.S_IMODE(path.parent.stat().st_mode)&0o077:
            raise ErroUploadAgro('diretorio JSONL nao privado 0700')
    if not 0<path.stat().st_size<=_MAX_BYTES:
        raise ErroUploadAgro('arquivo vazio/grande')
    digest=sha256()
    linhas=0
    fontes=set()
    with path.open('rb') as f:
        for raw in f:
            linhas+=1
            if linhas>_MAX_LINES or len(raw)>4096:
                raise ErroUploadAgro('limite de linhas/tamanho JSONL')
            digest.update(raw)
            try:
                item=json.loads(raw.decode('utf-8'))
            except (UnicodeError,ValueError) as exc:
                raise ErroUploadAgro('JSONL invalido') from exc
            if not isinstance(item,dict) or set(item)!=set(_FIELDS):
                raise ErroUploadAgro('schema JSONL inesperado')
            if item.get('status')!='QUARENTENA_NAO_PUBLICAVEL':
                raise ErroUploadAgro('somente quarentena pode chegar a staging')
            if not isinstance(item.get('source_sha256'),str) or not re.fullmatch(r'[0-9a-f]{64}',item['source_sha256']):
                raise ErroUploadAgro('SHA da fonte invalido')
            if not isinstance(item.get('valor'),str) or not re.fullmatch(r'-?\d+(?:\.\d+)?',item['valor']):
                raise ErroUploadAgro('valor nao decimal')
            fontes.add(item['source_id'])
    if linhas==0:
        raise ErroUploadAgro('arquivo sem linhas')
    return {'sha256_jsonl':digest.hexdigest(),'linhas':linhas,
            'bytes':path.stat().st_size,'fontes':sorted(fontes),'arquivo':str(path)}


def carregar_bigquery(*,arquivo:str|Path,projeto:str,dataset:str,
                     executar:bool=False,custos_autorizados:bool=False,
                     armazenamento_autorizado:bool=False,licencas_conferidas:bool=False,
                     cliente=None,tipos_bq=None,tipo_nao_encontrado=None)->dict:
    """Preflight local por padrão, cloud somente com quatro flags e dataset preexistente."""
    info=validar_lote(arquivo)
    if not isinstance(projeto,str) or not re.fullmatch(r'[a-z][a-z0-9-]{4,61}[a-z0-9]',projeto):
        raise ErroUploadAgro('project ID invalido')
    if not isinstance(dataset,str) or not re.fullmatch(r'[a-zA-Z_][a-zA-Z0-9_]{0,120}',dataset):
        raise ErroUploadAgro('dataset ID invalido')
    tabela=f'{projeto}.{dataset}.{_TABELA}'
    if not executar:
        return {**info,'tabela_planejada':tabela,
                'status':'PREFLIGHT_LOCAL_SEM_CLOUD',
                'job_executado':False,'cobranca_possivel':False}
    if (custos_autorizados is not True or armazenamento_autorizado is not True
            or licencas_conferidas is not True):
        raise PermissionError('BIGQUERY exige custo, armazenamento e licencas aprovados')
    # Toda carga em producao passa por MERGE insert-only para evitar
    # duplicidade entre lotes sobrepostos e historico completo.
    from .agro_bigquery_merge import mesclar_bigquery
    return mesclar_bigquery(
        info=info,arquivo=arquivo,projeto=projeto,dataset=dataset,
        cliente=cliente,tipos_bq=tipos_bq,
        tipo_nao_encontrado=tipo_nao_encontrado)


def main():
    p=argparse.ArgumentParser(description='NIVON: stage agro JSONL -> BigQuery (preflight por padrao)')
    p.add_argument('--arquivo',required=True)
    p.add_argument('--projeto',required=True)
    p.add_argument('--dataset',required=True)
    p.add_argument('--executar',action='store_true')
    p.add_argument('--custos-autorizados',action='store_true')
    p.add_argument('--armazenamento-autorizado',action='store_true')
    p.add_argument('--licencas-conferidas',action='store_true')
    a=p.parse_args()
    resultado=carregar_bigquery(arquivo=a.arquivo,projeto=a.projeto,dataset=a.dataset,
        executar=a.executar,custos_autorizados=a.custos_autorizados,
        armazenamento_autorizado=a.armazenamento_autorizado,
        licencas_conferidas=a.licencas_conferidas)
    print(json.dumps(resultado,ensure_ascii=False,sort_keys=True))


if __name__=='__main__':
    main()
