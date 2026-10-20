"""Verificação pontual do cabeçalho de 4 CSVs MDIC/Comex Stat oficiais.

Nunca imprime linhas/valores, nunca segue redirect, lê no máximo 4 KB por
arquivo, não persiste conteúdo. Só rodar manualmente --explicit-yes.
"""
from __future__ import annotations
import csv
import json
from urllib.request import Request,build_opener,HTTPRedirectHandler
from urllib.error import HTTPError,URLError

from nivon.mdic_exportacao import HEADER as EXP
from nivon.mdic_importacao import COLUNAS as IMP
from nivon.mdic_municipios import CABECALHO as MUN

HOST="https://balanca.mdic.gov.br/balanca/bd/comexstat-bd/"
DATASETS={
    "NCM_EXPORTACAO":(HOST+"ncm/EXP_2026.csv",EXP),
    "NCM_IMPORTACAO":(HOST+"ncm/IMP_2026.csv",IMP),
    "SH4_EXPORTACAO":(HOST+"mun/EXP_2026_MUN.csv",MUN),
    "SH4_IMPORTACAO":(HOST+"mun/IMP_2026_MUN.csv",MUN),
}

class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(self,req,fp,code,msg,headers,newurl):return None

def conferir(*,abridor=None):
    client=abridor if abridor is not None else build_opener(_NoRedirect())
    saida=[]
    for name,(url,esperado) in DATASETS.items():
        req=Request(url,headers={"User-Agent":"NIVON/0.2 schema-only",
                                 "Range":"bytes=0-4095","Accept":"text/csv,text/plain,application/octet-stream"})
        try:
            with client.open(req,timeout=12) as r:
                if r.status not in (200,206) or r.geturl()!=url:
                    saida.append({"dataset":name,"estado":"STATUS_OU_REDIRECT_INCORRETO"})
                    continue
                tipo=r.headers.get("Content-Type","").lower().split(";",1)[0]
                if tipo not in ("text/plain","text/csv","application/csv",
                                "application/octet-stream","application/vnd.ms-excel"):
                    saida.append({"dataset":name,"estado":"MIME_INESPERADO","mime":tipo[:60]})
                    continue
                b=r.read(4096)
        except (URLError,HTTPError,OSError,TimeoutError) as exc:
            saida.append({"dataset":name,"estado":"INACESSIVEL","erro_tipo":type(exc).__name__})
            continue
        try:
            line=b.decode("utf-8-sig",errors="strict").splitlines()[0]
            fields=next(csv.reader([line],delimiter=";"))
        except (UnicodeError,IndexError,csv.Error):
            saida.append({"dataset":name,"estado":"HEADER_NAO_DECODIFICAVEL"})
            continue
        saida.append({"dataset":name,"estado":"HEADER_IGUAL" if tuple(fields)==esperado else "HEADER_DIVERGENTE",
                     "colunas_recebidas":len(fields),"colunas_esperadas":len(esperado),
                     "linhas_individuais_publicadas":0})
    return saida

def main(argv=None):
    import argparse
    parser=argparse.ArgumentParser()
    parser.add_argument("--explicit-yes",action="store_true")
    opts=parser.parse_args(argv)
    if not opts.explicit_yes:
        print(json.dumps({"estado":"DESABILITADO_POR_PADRAO"}))
        return 2
    print(json.dumps(conferir(),ensure_ascii=False))
    return 0

if __name__=="__main__":
    raise SystemExit(main())
