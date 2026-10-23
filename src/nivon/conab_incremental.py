"""Atualização incremental CONAB em lote, com histórico versionado.

Uma consulta ao índice, no máximo N semanas oficiais, cada XLSX validado
e importação de todos os pacotes em SQLite. Execução CLI sob flags
explícitas, sem agendamento, publicação ou gravação em Google Cloud.
"""
from __future__ import annotations

import argparse
import json
from datetime import datetime

from .conab_indice_progresso import consultar_indice
from .conab_execucao_edicao import executar_edicao_conab
from .conab_quarentena_real import importar_pacotes_locais


class ErroIncrementalConab(ValueError):
    pass


def atualizar_conab_lote(*,banco,raw_dir,quantidade:int=2,
                        executar:bool=False,direitos_consulta:bool=False,
                        direitos_coleta:bool=False,direitos_armazenamento:bool=False,
                        buscar_indice=consultar_indice,
                        executar_semana=executar_edicao_conab,
                        importar=importar_pacotes_locais,
                        abridor=None,transport=None)->dict:
    if not all(x is True for x in
        (executar,direitos_consulta,direitos_coleta,direitos_armazenamento)):
        raise PermissionError('lote CONAB requer direitos e execucao explicitamente autorizados')
    if type(quantidade) is not int or not 1<=quantidade<=4:
        raise ErroIncrementalConab('lote limitado a 1-4 semanas por execucao')
    idx=buscar_indice(executar=True,abridor=abridor)
    candidatos=idx.get('edicoes_candidatas',[])
    if not isinstance(candidatos,list) or not candidatos:
        return {'status':'INDICE_SEM_EDICOES','semanas':0,'publicacao_permitida':False}
    selecionados=candidatos[:quantidade]
    selecionados_ids=[]
    capturas=[]
    for item in selecionados:
        try:
            fim=datetime.strptime(item['periodo_rotulo'].split(' a ')[-1],'%d/%m/%y').date().isoformat()
        except (ValueError,AttributeError,KeyError) as exc:
            raise ErroIncrementalConab('rótulo semanal não canônico no índice') from exc
        if fim in selecionados_ids:
            raise ErroIncrementalConab('dupla contagem de edicao semanal no indice')
        selecionados_ids.append(fim)
        r=executar_semana(
            banco=banco,raw_dir=raw_dir,semana_fim=fim,
            autorizado=True,direitos_consulta=True,direitos_coleta=True,
            direitos_armazenamento=True,
            buscar_indice=lambda *,executar,abridor=None: idx,
            abridor=abridor,transport=transport)
        if r.get('status') not in (
            'CAPTURA_PONTUAL_CONAB_NAO_PUBLICAVEL',
            'EDICAO_RAW_ANTERIOR_VERIFICADA_SEM_REDOWLOAD'):
            raise ErroIncrementalConab('semana não foi capturada ou revalidada')
        capturas.append({'semana_fim':fim,'id_edicao':r['edicao_id'],
                         'estado':r['status'],
                         'sha256':r.get('sha256_raw') or r.get('evidencia',{}).get('sha256')})
    q=importar(banco=banco,raiz=raw_dir,executar=True,direitos_armazenamento=True)
    if q.get('publicacao_permitida') is not False:
        raise ErroIncrementalConab('retorno indevido de publicação')
    # "observacoes" é a soma por edição/versão reprocessada no lote;
    # não significa soma física nacional ou dias de fluxo.
    return {
        'status':'LOTE_REAL_EM_QUARENTENA_LOCAL',
        'semanas_solicitadas':quantidade,
        'semanas_processadas':len(capturas),
        'edicoes':capturas,
        'versoes_novas_na_quarentena':q.get('versoes_novas'),
        'observacoes_reprocessadas':q.get('observacoes_processadas'),
        'arquivos_locais_processados':q.get('arquivos_importados'),
        'cloud_gravado':False,'publicacao_permitida':False
    }


def main():
    p=argparse.ArgumentParser(description='CONAB NIVON: lote incremental histórico (quarentena local)')
    p.add_argument('--banco',required=True)
    p.add_argument('--pasta-raw',required=True)
    p.add_argument('--quantidade',type=int,default=2)
    p.add_argument('--executar',action='store_true')
    p.add_argument('--direitos-consulta',action='store_true')
    p.add_argument('--direitos-coleta',action='store_true')
    p.add_argument('--direitos-armazenamento',action='store_true')
    a=p.parse_args()
    out=atualizar_conab_lote(
        banco=a.banco,raw_dir=a.pasta_raw,quantidade=a.quantidade,
        executar=a.executar,direitos_consulta=a.direitos_consulta,
        direitos_coleta=a.direitos_coleta,direitos_armazenamento=a.direitos_armazenamento)
    print(json.dumps(out,ensure_ascii=False,sort_keys=True))


if __name__=='__main__':
    main()
