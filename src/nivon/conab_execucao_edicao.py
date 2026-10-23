"""CONAB: uma execução supervisionada índice -> documento -> XLSX RAW.

Não agenda, não publica e não conecta Cloud. Downloads só ocorrem após
flags explicitas e com URL literal extraída de um <a> do portal oficial.
A validação do XLSX é feita pelo parser de progresso já existente.
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import re
import sqlite3
import stat
from hashlib import sha256

from .conab_indice_progresso import ErroIndiceConab, consultar_indice
from .conab_sync_metadados import consultar_pagina_semana
from .conab_fila_publicacoes import atualizar_fila, proximos_arquivos
from .conab_resolver_anexo import (
    resolver_html_documento, registrar_resolucao, montar_registro_captura
)
from .captura_xlsx_conab import capturar_xlsx_conab, verificar_pacote_captura_local


class ErroExecucaoConab(ValueError):
    pass


def _privado(path:Path):
    if not path.is_dir() or path.is_symlink():
        raise ErroExecucaoConab('diretorio privado existente obrigatorio')
    if os.name=='posix' and (stat.S_IMODE(path.stat().st_mode)&0o077):
        raise ErroExecucaoConab('diretorio precisa modo 0700')


def executar_edicao_conab(*,banco:str|Path,raw_dir:str|Path,
                          autorizado:bool=False,
                          direitos_consulta:bool=False,
                          direitos_coleta:bool=False,
                          direitos_armazenamento:bool=False,
                          buscar_indice=consultar_indice,
                          buscar_pagina=consultar_pagina_semana,
                          capturar=capturar_xlsx_conab,
                          verificar=verificar_pacote_captura_local,
                          abridor=None,transport=None)->dict:
    """Coleta no máximo UMA edição/arquivo por comando, com evidências RAW.

    O download real ocorre no capturador, não na fila. Toda captura que
    parece sucesso, mas não tem bytes, é responsabilidade do capturador:
    o teste de produção deve usar o capturador oficial e seu manifesto.
    """
    if not all(x is True for x in
        (autorizado,direitos_consulta,direitos_coleta,direitos_armazenamento)):
        raise PermissionError('CONAB: autorizar consulta, coleta e armazenamento')
    raiz=Path(raw_dir)
    _privado(raiz)
    path=Path(banco)
    if path.is_symlink() or not path.parent.is_dir():
        raise ErroExecucaoConab('arquivo SQLite deve estar em local existente')
    if os.name=='posix' and (stat.S_IMODE(path.parent.stat().st_mode)&0o077):
        raise ErroExecucaoConab('SQLite deve ficar em diretorio privado 0700')
    indice=buscar_indice(executar=True,abridor=abridor)
    edicoes=indice.get('edicoes_candidatas',[])
    if not edicoes:
        return {'status':'SEM_EDICAO_NO_INDICE','capturas':0}
    edicao=edicoes[0] # O indice apresenta as semanas mais recentes primeiro.
    pagina_url=edicao['pagina_oficial']
    pagina_html=buscar_pagina(pagina_url,executar=True,direitos_consulta=True,abridor=abridor)
    db=sqlite3.connect(str(path),timeout=20)
    try:
        novos=atualizar_fila(db,indice=indice,paginas={pagina_url:pagina_html})
        links=[r for r in proximos_arquivos(db,limite=100)
               if r['pagina_url']==pagina_url and r['tipo']=='PLANTIO_COLHEITA']
        if len(links)!=1:
            raise ErroExecucaoConab('edicão deve conter um link único de plantio/colheita')
        doc=links[0]['url']
        html_doc=buscar_pagina(doc,executar=True,direitos_consulta=True,abridor=abridor)
        # Timestamp do indice e a hora de COLETA dos links, nao a data de publicação.
        from datetime import datetime
        coleta=datetime.fromisoformat(indice['coletado_em'])
        resolvido=resolver_html_documento(html_doc,pagina_semana=pagina_url,
                                          url_documento=doc,coletado_em=coleta)
        registro=montar_registro_captura(indice_semana=edicao,resolucao=resolvido)
        persistido=registrar_resolucao(db,resolucao=resolvido)
    finally:
        db.close()

    # Revisões com outro URL recebem diretórios distintos. Rerun do MESMO
    # recurso verifica RAW/evidência existentes, nunca substitui arquivos.
    hash_url=sha256(resolvido['url_anexo'].encode('utf-8')).hexdigest()[:16]
    pasta=raiz/(registro['id_edicao']+'_'+hash_url)
    if pasta.exists():
        _privado(pasta)
        if not list(pasta.iterdir()):
            raise ErroExecucaoConab('pasta anterior vazia: investigar tentativa interrompida')
        antigo=verificar(registro,pasta)
        return {'status':'EDICAO_RAW_ANTERIOR_VERIFICADA_SEM_REDOWLOAD',
                'edicao_id':registro['id_edicao'],'arquivo_dir':str(pasta),
                'evidencia':antigo,'novas_semanas':novos['novas_semanas'],
                'documento_novo':persistido['novo'],'publicado_no_nivon':False}
    pasta.mkdir(mode=0o700)
    try:
        capturado=capturar(
            registro,destino=pasta,
            autoriza_requisicao=True,direitos_coleta_conferidos=True,
            transport=transport)
    except BaseException:
        # Em erros antes de gravar RAW, remover só diretório vazio criado
        # nesta execução. Se houver evidência parcial, preservar para auditoria.
        if not list(pasta.iterdir()):
            pasta.rmdir()
        raise
    if capturado.get('publicacao_permitida') is not False:
        raise ErroExecucaoConab('capturador retornou publicação indevida')
    return {'status':'CAPTURA_PONTUAL_CONAB_NAO_PUBLICAVEL',
            'edicao_id':registro['id_edicao'],'arquivo_dir':str(pasta),
            'sha256_raw':capturado.get('raw_sha256'),
            'quantidade_observacoes':capturado.get('quantidade_observacoes'),
            'novas_semanas':novos['novas_semanas'],
            'documento_novo':persistido['novo'],
            'publicado_no_nivon':False,'google_cloud_gravado':False}


def main():
    p=argparse.ArgumentParser(description='NIVON CONAB: capturar uma edição XLSX autorizada')
    p.add_argument('--banco',required=True)
    p.add_argument('--pasta-raw',required=True)
    p.add_argument('--executar',action='store_true')
    p.add_argument('--direitos-consulta',action='store_true')
    p.add_argument('--direitos-coleta',action='store_true')
    p.add_argument('--direitos-armazenamento',action='store_true')
    args=p.parse_args()
    res=executar_edicao_conab(
        banco=args.banco,raw_dir=args.pasta_raw,autorizado=args.executar,
        direitos_consulta=args.direitos_consulta,
        direitos_coleta=args.direitos_coleta,
        direitos_armazenamento=args.direitos_armazenamento
    )
    print(json.dumps(res,sort_keys=True,ensure_ascii=False))


if __name__=='__main__':
    main()
