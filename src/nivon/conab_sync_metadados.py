"""Sincronizador EXPLICITO de metadados CONAB, sem baixar XLSX.

Fluxo real controlado:
  GET indice oficial -> GET ate N paginas semanais -> fila SQLite persistida.
Nao dispara GET se a consulta nao for autorizada, nem agenda execucao.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sqlite3
from urllib.request import Request, HTTPRedirectHandler, ProxyHandler, build_opener

from .conab_indice_progresso import (
    ErroIndiceConab, _url_valida, consultar_indice,
)
from .conab_fila_publicacoes import atualizar_fila, examinar_pagina_semana, proximos_arquivos

MAX_HTML = 2_000_000


class _SemRedirect(HTTPRedirectHandler):
    def redirect_request(self, request, fp, code, msg, headers, newurl):
        return None


def consultar_pagina_semana(url: str, *, executar: bool=False,
                           direitos_consulta: bool=False, abridor=None) -> bytes:
    if executar is not True or direitos_consulta is not True:
        raise PermissionError('leitura de pagina CONAB exige autorizacao')
    if not _url_valida(url):
        raise ErroIndiceConab('pagina nao autorizada')
    cliente=abridor if abridor is not None else build_opener(ProxyHandler({}),_SemRedirect())
    req=Request(url,headers={'Accept':'text/html','User-Agent':'NIVON/0.1 (metadados publicos)'})
    with cliente.open(req,timeout=20) as resp:
        if int(resp.status)!=200 or resp.geturl()!=url:
            raise ErroIndiceConab('resposta HTTP ou redirecionamento invalido')
        mime=str(resp.headers.get('Content-Type','')).split(';',1)[0].strip().lower()
        if mime not in {'text/html','application/xhtml+xml'}:
            raise ErroIndiceConab('mime nao HTML')
        raw=resp.read(MAX_HTML+1)
    examinar_pagina_semana(raw,pagina_url=url)
    return raw


def sincronizar_indice_conab(db:sqlite3.Connection, *, executar:bool=False,
                            direitos_consulta:bool=False, limite_paginas:int=3,
                            abridor=None, consulta_indice=consultar_indice,
                            consulta_semana=consultar_pagina_semana) -> dict:
    if executar is not True or direitos_consulta is not True:
        raise PermissionError('sincronizacao CONAB exige consulta autorizada')
    if type(limite_paginas) is not int or not 1<=limite_paginas<=10:
        raise ErroIndiceConab('limite de paginas por chamada fora do contrato')
    indice=consulta_indice(executar=True,abridor=abridor)
    paginas={}
    for item in indice.get('edicoes_candidatas',[])[:limite_paginas]:
        url=item['pagina_oficial']
        paginas[url]=consulta_semana(url,executar=True,direitos_consulta=True,abridor=abridor)
    resultado=atualizar_fila(db,indice=indice,paginas=paginas)
    return {**resultado,'arquivos_pendentes':db.execute("SELECT count(*) FROM conab_documentos_candidatos WHERE fase='PENDENTE_VALIDACAO'").fetchone()[0],
            'coleta_de_planilhas':False,'registro_de_publicacao_confirmado':False,
            'modo':'METADADOS_APENAS'}


def main():
    p=argparse.ArgumentParser(description='NIVON CONAB: sincronizar metadados em SQLite local')
    p.add_argument('--banco',required=True)
    p.add_argument('--limite-paginas',type=int,default=3)
    p.add_argument('--executar',action='store_true')
    p.add_argument('--direitos-consulta',action='store_true')
    args=p.parse_args()
    if not args.executar or not args.direitos_consulta:
        p.error('use --executar --direitos-consulta após verificar permissões')
    banco=Path(args.banco)
    db=sqlite3.connect(str(banco),timeout=20)
    try:
        result=sincronizar_indice_conab(db,executar=args.executar,
                   direitos_consulta=args.direitos_consulta,limite_paginas=args.limite_paginas)
    finally:
        db.close()
    print(json.dumps(result,ensure_ascii=False,sort_keys=True))


if __name__=='__main__':
    main()
