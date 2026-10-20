"""CLI E2E NIVON em modo ensaio, usando pacotes e SQLite locais autorizados.

Exemplo:
PYTHONPATH=src python -m nivon.ensaio_vertical \
 --entrada autorizada.json --contratos escopo.json \
 --db-conab /volume/progresso.sqlite --db-portos /volume/portos.sqlite \
 --gerado-em 2026-10-20T08:00:00-03:00 --saida /volume/briefing.txt

NUNCA agenda, envia WhatsApp, acessa rede, atribui licença ou escreve no
banco histórico. Saída TXT é pessoal, criada em 0600 e nunca sobrescrita.
"""
from __future__ import annotations

import argparse
from contextlib import closing
import json
import os
from pathlib import Path
import sqlite3
import sys
from urllib.parse import quote

from .indicadores_historicos import compor_pacote_historico
from .rotina_diaria import preparar_rotina


class ErroEnsaio(ValueError):
    pass


def _json(path: str) -> dict:
    p=Path(path)
    if p.is_symlink() or not p.is_file() or p.stat().st_size>2_000_000:
        raise ErroEnsaio("JSON de entrada ausente, link ou excessivo")
    data=json.loads(p.read_text(encoding="utf-8"))
    if not isinstance(data,dict):
        raise ErroEnsaio("JSON raiz deve ser objeto")
    return data


def _sqlite_ro(path: str | None):
    if path is None:
        return None
    p=Path(path)
    if p.is_symlink() or not p.is_file() or p.stat().st_size>2_000_000_000:
        raise ErroEnsaio("SQLite ausente, link ou excessivo")
    uri="file:"+quote(str(p.absolute()),safe="/")+"?mode=ro"
    conn=sqlite3.connect(uri,uri=True,timeout=5)
    conn.row_factory=sqlite3.Row
    conn.execute("PRAGMA query_only=ON")
    return conn


def _saida_segura(path: str, texto: str) -> int:
    p=Path(path)
    if not p.parent.is_dir() or p.parent.is_symlink():
        raise ErroEnsaio("diretório de saída inválido")
    data=(texto+"\n").encode("utf-8")
    if len(data)>500_000:
        raise ErroEnsaio("briefing acima de 500 kB")
    fd=None
    try:
        fd=os.open(p,os.O_CREAT | os.O_EXCL | os.O_WRONLY | getattr(os,"O_NOFOLLOW",0),0o600)
        with os.fdopen(fd,"wb") as f:
            fd=None
            f.write(data)
            f.flush()
            os.fsync(f.fileno())
    finally:
        if fd is not None:
            os.close(fd)
    return len(data)


def executar(argv=None) -> dict:
    parser=argparse.ArgumentParser(description="NIVON E2E offline, nunca envia")
    parser.add_argument("--entrada",required=True)
    parser.add_argument("--contratos",required=True)
    parser.add_argument("--db-conab",default=None)
    parser.add_argument("--db-portos",default=None)
    parser.add_argument("--db-mercados",default=None)
    parser.add_argument("--db-diesel",default=None)
    parser.add_argument("--licencas-mercados",default=None)
    parser.add_argument("--incluir-ptax-usd",action="store_true")
    parser.add_argument("--gerado-em",required=True)
    parser.add_argument("--saida",required=True)
    args=parser.parse_args(argv)
    pacote=_json(args.entrada)
    licencas=_json(args.licencas_mercados) if args.licencas_mercados else {}
    contratos=_json(args.contratos)
    cultures=contratos.get("culturas",[])
    ports=contratos.get("portos",[])
    diesel=contratos.get("diesel",[])
    if (not isinstance(cultures,list) or not isinstance(ports,list)
        or len(cultures)>30 or len(ports)>45
        or not all(isinstance(c,dict) for c in cultures)
        or not all(isinstance(p,str) and 0<len(p)<=80 for p in ports)
        or not isinstance(diesel,list) or len(diesel)>40
        or not all(isinstance(x,dict) and set(x)=={"uf","municipio","produto"}
                   for x in diesel)):
        raise ErroEnsaio("contratos de safra/portos inválidos")
    with closing(_sqlite_ro(args.db_conab)) if args.db_conab else _NoConn() as c:
        with closing(_sqlite_ro(args.db_portos)) if args.db_portos else _NoConn() as p:
            with closing(_sqlite_ro(args.db_mercados)) if args.db_mercados else _NoConn() as m:
                with closing(_sqlite_ro(args.db_diesel)) if args.db_diesel else _NoConn() as d:
                    return _executar_com_bancos(args,pacote,cultures,ports,diesel,c,p,m,d,licencas)


def _executar_com_bancos(args, pacote, cultures, ports, diesel, c, p, m, d, licencas):
            dados=compor_pacote_historico(
                db_conab=c,db_portos=p,db_mercados=m,
                db_diesel=d,diesel_localidades=diesel,
                cotacoes_licenciadas=pacote.get("cotacoes_licenciadas"),
                licencas_verificadas=licencas,
                incluir_ptax_usd=args.incluir_ptax_usd,gerado_em=args.gerado_em,
                fontes=pacote.get("fontes",{}),
                noticias=pacote.get("noticias",[]),
                indicadores_externos=pacote.get("indicadores",[]),
                fretes=pacote.get("fretes",[]),
                culturas=cultures,portos=ports,
            )
            falhas=[x for x in dados["resultados"]
                    if x["status"]!="INDICADOR_VERIFICADO_TEMPO"]
            if falhas:
                return {"status":"BLOQUEADO_HISTORICO_INCOMPLETO",
                        "falhas":[{"origem":x["origem"],"motivo":x.get("motivo",x["status"])}
                                  for x in falhas],
                        "arquivo_criado":False}
            check=preparar_rotina(
                pacote=dados["pacote"],gerado_em=args.gerado_em,
                auditor=lambda b: len(b["rejeicoes"])==0,agendar=False,
            )
            if check["status"]!="VALIDADO_DRY_RUN":
                return {"status":check["status"],
                        "arquivo_criado":False,
                        "faltam":check.get("faltam",[])}
            n=_saida_segura(args.saida,check["texto"])
            return {"status":"ENSAIO_OFFLINE_VALIDADO",
                    "arquivo_criado":True,"bytes":n,
                    "transmissao_whatsapp":False,
                    "indicadores_historicos":len(dados["resultados"])}


class _NoConn:
    def __enter__(self): return None
    def __exit__(self,*_): return False


def main(argv=None) -> int:
    try:
        resultado=executar(argv)
        print(json.dumps(resultado,ensure_ascii=False))
        return 0 if resultado["status"]=="ENSAIO_OFFLINE_VALIDADO" else 3
    except (OSError,ValueError,TypeError,KeyError,sqlite3.Error,
            UnicodeError,json.JSONDecodeError) as exc:
        print(json.dumps({"status":"ENSAIO_FALHOU","erro":type(exc).__name__},
                         ensure_ascii=False),file=sys.stderr)
        return 2


if __name__=="__main__":
    raise SystemExit(main())
