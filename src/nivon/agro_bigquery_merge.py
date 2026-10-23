"""BigQuery staging seguro: LOAD em tabela de lote, MERGE somente de linhas ausentes.

Somente executor autorizado pode criar tabela temporaria, fazer MERGE,
excluir tabela temporaria e incorrer custos. Nao cria projetos/datasets e
nao publica em motores. IDs determinísticos tornam a repeticao de um
lote rastreavel; comparar valores entre vintages e competencia segue QA.
"""
from __future__ import annotations

from hashlib import sha256

from .agro_bigquery_loader import ErroUploadAgro, _FIELDS, _TIPOS, _TABELA

# Sem update/delete: preserva vintages anteriores e novos registros.
# Todos os campos participam da identidade exata e comparação NULL-safe.
_COLUNAS=tuple(_FIELDS)


def sql_mesclagem(*, origem:str, destino:str)->str:
    """SQL gerado apenas a partir de IDs validados pelo loader."""
    for v in (origem,destino):
        if not isinstance(v,str) or len(v.split('.'))!=3:
            raise ErroUploadAgro('identificador BigQuery deve ter projeto.dataset.tabela')
        if any(not part or not all(c.isalnum() or c in '_-' for c in part)
               for part in v.split('.')):
            raise ErroUploadAgro('identificador BigQuery invalido')
    campos=', '.join(_COLUNAS)
    valores=', '.join('S.'+k for k in _COLUNAS)
    comparacoes=' AND\n    '.join('T.'+k+' IS NOT DISTINCT FROM S.'+k for k in _COLUNAS)
    return (
        f'MERGE \`{destino}\` AS T\n'
        f'USING (SELECT DISTINCT {campos} FROM \`{origem}\`) AS S\n'
        f'ON {comparacoes}\n'
        f'WHEN NOT MATCHED THEN INSERT ({campos}) VALUES ({valores})'
    ).replace('\\`','`')


def mesclar_bigquery(*, info:dict, arquivo, projeto:str, dataset:str,
                     cliente=None, tipos_bq=None, tipo_nao_encontrado=None,
                     max_bytes_cobraveis:int=1_000_000_000) -> dict:
    """Executado APENAS apos flags de custo/licenca/direitos no loader."""
    if type(max_bytes_cobraveis) is not int or not 100_000_000<=max_bytes_cobraveis<=20_000_000_000:
        raise ErroUploadAgro('limite de custos bytes invalidos')
    if cliente is None or tipos_bq is None:
        try:
            from google.cloud import bigquery
        except ImportError as exc:
            raise RuntimeError('instale google-cloud-bigquery no executor autorizado') from exc
        cliente=cliente if cliente is not None else bigquery.Client(project=projeto)
        tipos_bq=tipos_bq if tipos_bq is not None else bigquery
    if tipo_nao_encontrado is None:
        try:
            from google.api_core.exceptions import NotFound as tipo_nao_encontrado
        except ImportError as exc:
            raise RuntimeError('google-api-core nao instalado') from exc

    destino=f'{projeto}.{dataset}.{_TABELA}'
    table=cliente.get_table(destino)
    tipos={x.name:x.field_type.upper() for x in table.schema}
    if tipos!=_TIPOS:
        raise ErroUploadAgro('schema BigQuery nao coincide com contrato de staging')
    local=getattr(table,'location',None)
    if not isinstance(local,str) or not local:
        raise ErroUploadAgro('localizacao BigQuery nao verificada')

    uid=sha256((destino+':'+info['sha256_jsonl']).encode('utf-8')).hexdigest()[:36]
    lote=f'{projeto}.{dataset}._nivon_agro_lote_{uid}'
    load_id='nivon_agro_load_'+uid
    merge_id='nivon_agro_merge_'+uid
    def _job_ou_none(job_id):
        try:
            return cliente.get_job(job_id,location=local)
        except tipo_nao_encontrado:
            return None

    # A etapa conclusiva (MERGE) e verificada PRIMEIRO.
    # Quando ja finalizada, jamais refaz carga; preserva idempotencia.
    concluido=_job_ou_none(merge_id)
    if concluido is not None:
        concluido.result(timeout=180)
        if getattr(concluido,'error_result',None):
            raise ErroUploadAgro('job de MERGE anterior falhou: inspecao operacional')
        return {**info,'tabela':destino,'job_id':merge_id,
                'status':'MERGE_JA_CONCLUIDO_NAO_REPROCESSAR',
                'job_executado':False,'dados_publicados':False}

    load=_job_ou_none(load_id)
    if load is None:
        config=tipos_bq.LoadJobConfig(
            source_format=tipos_bq.SourceFormat.NEWLINE_DELIMITED_JSON,
            write_disposition=tipos_bq.WriteDisposition.WRITE_EMPTY,
            autodetect=False,
            schema=table.schema
        )
        with open(arquivo,'rb') as data:
            load=cliente.load_table_from_file(
                data,destination=lote,job_config=config,job_id=load_id,location=local)
    load.result(timeout=180)
    if getattr(load,'error_result',None):
        raise ErroUploadAgro('job de carga de lote falhou: investigar antes de repetir')
    # Nao atribuir carga parcial se tabela do lote desapareceu entre fases.
    temp=cliente.get_table(lote)
    if {x.name:x.field_type.upper() for x in temp.schema}!=_TIPOS:
        raise ErroUploadAgro('schema do lote temporario diverge')

    query=sql_mesclagem(origem=lote,destino=destino)
    # INSERT-only MERGE atomico, sem apagar vintages do alvo.
    config_sql=tipos_bq.QueryJobConfig(use_legacy_sql=False,
                                       maximum_bytes_billed=max_bytes_cobraveis)
    job=cliente.query(query,job_config=config_sql,job_id=merge_id,location=local)
    job.result(timeout=180)
    if getattr(job,'error_result',None):
        raise ErroUploadAgro('MERGE falhou; lote intermediario retido para auditoria')
    try:
        cliente.delete_table(lote,not_found_ok=True)
        limpeza=True
    except Exception:
        limpeza=False
    return {**info,'tabela':destino,'job_id':merge_id,
            'status':'MERGE_CONCLUIDO_NAO_PUBLICAVEL',
            'job_executado':True,'tabela_lote_removida':limpeza,
            'dados_publicados':False}
