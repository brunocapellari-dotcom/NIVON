"""Um comando para consolidar bases e validar/cargar lotes BigQuery.

O modo padrao (preflight) nao acessa GCP, nao escreve em tabelas Cloud,
nao busca na internet e nao cria infraestrutura. Uso real requer flags
explicitas e registra progresso por lote num manifesto privado.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from .agro_consolidar_multibancos import consolidar_sqlites
from .agro_bigquery_loader import carregar_bigquery

class ErroOperacaoAgro(ValueError):
    pass


def operar_agro(*, bancos:list, pasta_saida:str|Path,
               projeto:str, dataset:str, prefixo:str='agro',
               max_linhas_por_lote:int=25000,
               executar_cloud:bool=False, custos_autorizados:bool=False,
               armazenamento_autorizado:bool=False,
               licencas_conferidas:bool=False,
               cliente=None,tipos_bq=None,tipo_nao_encontrado=None)->dict:
    """Pipeline fonte SQLite -> manifestos -> preflight -> MERGE opcional.

    Evitar operacoes parciais silenciosas: retorna trabalhos concluidos
    e interrompe a primeira falha. Reexecucao do MESMO lote sob IDs
    determinísticos e reconciliavel por jobs do BigQuery.
    """
    if type(executar_cloud) is not bool:
        raise ErroOperacaoAgro('modo executar_cloud deve ser booleano')
    if executar_cloud and not all(x is True for x in
        (custos_autorizados,armazenamento_autorizado,licencas_conferidas)):
        raise PermissionError('gates CLOUD de custo/licenca/armazenamento incompletos')
    consolidado=consolidar_sqlites(
        bancos=bancos,pasta_saida=pasta_saida,prefixo=prefixo,
        max_linhas_por_lote=max_linhas_por_lote
    )
    past=Path(pasta_saida)
    # SEMPRE testar preflight de TODOS os shards antes de qualquer cloud.
    preflight=[]
    for parte in consolidado['lotes']:
        r=carregar_bigquery(arquivo=past/parte['arquivo'],projeto=projeto,dataset=dataset)
        if r['sha256_jsonl']!=parte['sha256_jsonl'] or r['linhas']!=parte['linhas']:
            raise ErroOperacaoAgro('lote nao confere com manifesto')
        preflight.append({
            'arquivo':parte['arquivo'],'sha256_jsonl':parte['sha256_jsonl'],
            'linhas':parte['linhas'],'estado':r['status']
        })
    out={'manifesto':consolidado['manifesto'],
         'lotes':preflight,'linhas_distintas':consolidado['linhas_distintas'],
         'cloud_autorizado':executar_cloud,'cloud_concluido':False}
    if not executar_cloud:
        out['estado']='PREFLIGHT_INTEGRADO_APROVADO_SEM_REDE'
        return out
    confirmados=[]
    for parte in consolidado['lotes']:
        try:
            resposta=carregar_bigquery(
                arquivo=past/parte['arquivo'],projeto=projeto,dataset=dataset,
                executar=True,custos_autorizados=True,
                armazenamento_autorizado=True,licencas_conferidas=True,
                cliente=cliente,tipos_bq=tipos_bq,tipo_nao_encontrado=tipo_nao_encontrado
            )
        except Exception as exc:
            # Lotes anteriores continuam no BigQuery, nao ha rollback.
            # Os jobs sao idempotentes e devem ser reconciliados no reprocessamento.
            raise ErroOperacaoAgro(
                'falha de carga MERGE; lotes confirmados antes da falha: '
                +','.join(confirmados)+'; verifique jobs antes de repetir') from exc
        confirmados.append(parte['arquivo'])
        for item in preflight:
            if item['arquivo']==parte['arquivo']:
                item['estado']=resposta['status']
                item['job_id']=resposta['job_id']
                break
    out['cloud_concluido']=True
    out['estado']='MERGE_CONCLUIDO_APENAS_STAGING_NAO_PUBLICAVEL'
    return out


def main():
    p=argparse.ArgumentParser(description='NIVON central de fontes (preflight padrao)')
    p.add_argument('--banco',action='append',required=True)
    p.add_argument('--pasta-saida',required=True)
    p.add_argument('--projeto',required=True)
    p.add_argument('--dataset',required=True)
    p.add_argument('--prefixo',default='agro')
    p.add_argument('--max-linhas-por-lote',type=int,default=25000)
    p.add_argument('--executar-cloud',action='store_true')
    p.add_argument('--custos-autorizados',action='store_true')
    p.add_argument('--armazenamento-autorizado',action='store_true')
    p.add_argument('--licencas-conferidas',action='store_true')
    a=p.parse_args()
    result=operar_agro(
        bancos=a.banco,pasta_saida=a.pasta_saida,
        projeto=a.projeto,dataset=a.dataset,prefixo=a.prefixo,
        max_linhas_por_lote=a.max_linhas_por_lote,
        executar_cloud=a.executar_cloud,custos_autorizados=a.custos_autorizados,
        armazenamento_autorizado=a.armazenamento_autorizado,
        licencas_conferidas=a.licencas_conferidas
    )
    print(json.dumps(result,ensure_ascii=False,sort_keys=True))


if __name__=='__main__':
    main()
