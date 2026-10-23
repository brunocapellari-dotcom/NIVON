"""Importação atômica de um lote de arquivos PTAX externos em quarentena.

Sem rede, credenciais ou publicação. Manifesto do lote aponta somente
nomes de arquivo na própria pasta — sem symlinks, caminhos relativos com
pontos, subpastas, URLs ou expansão de curingas. Valida TODOS os itens
antes de iniciar transação SQLite, e cancela TUDO na primeira falha.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import re
import sqlite3

from nivon.ptax_quarentena_coleta import (
    ErroQuarentenaPTAX, MAX_BYTES, MAX_MANIFEST,
    validar_amostra_ptax, receber_amostra_ptax,
)
from nivon.transacoes_sqlite import savepoint_atomico


class ErroLoteQuarentenaPTAX(ValueError):
    """Lote inseguro, inconsistente, excessivo ou incompleto."""


MAX_LOTE=50
MAX_LOTE_BYTES=40_000_000
VERSAO="NIVON_PTAX_IMPORTACAO_LOTE_V1"
ARQUIVO_RE=re.compile(r"[A-Za-z0-9][A-Za-z0-9_-]{0,90}\.json\Z")


def _arquivo_pasta(pasta: Path, nome: str, limite: int) -> bytes:
    if not isinstance(nome, str) or not ARQUIVO_RE.fullmatch(nome):
        raise ErroLoteQuarentenaPTAX("nome de arquivo fora do padrão permitido")
    caminho=pasta/nome
    if caminho.is_symlink() or not caminho.is_file() or caminho.stat().st_size>limite:
        raise ErroLoteQuarentenaPTAX("arquivo ausente, symlink ou excessivo")
    with caminho.open("rb") as f:
        buffer=f.read(limite+1)
    if len(buffer)>limite:
        raise ErroLoteQuarentenaPTAX("arquivo acima do limite")
    return buffer


def importar_lote_ptax_quarentena(
    db: sqlite3.Connection, *, pasta: Path, lote: dict,
) -> dict:
    """Consome até 50 pares (raw, manifest) dentro da mesma pasta segura."""
    if not isinstance(db, sqlite3.Connection):
        raise ErroLoteQuarentenaPTAX("conexão SQLite obrigatória")
    pasta=Path(pasta)
    if pasta.is_symlink() or not pasta.is_dir():
        raise ErroLoteQuarentenaPTAX("pasta inválida")
    if not isinstance(lote, dict) or set(lote)!={"versao","capturas"} or (
        lote["versao"]!=VERSAO or
        not isinstance(lote["capturas"],list) or
        not 1<=len(lote["capturas"])<=MAX_LOTE
    ):
        raise ErroLoteQuarentenaPTAX("manifesto de lote inválido")
    itens=[]
    vistos=set()
    total_bytes=0
    for item in lote["capturas"]:
        if not isinstance(item,dict) or set(item)!={"raw","manifesto"}:
            raise ErroLoteQuarentenaPTAX("item do lote inválido")
        if item["raw"]==item["manifesto"] or (
            item["raw"],item["manifesto"]
        ) in vistos:
            raise ErroLoteQuarentenaPTAX("par de arquivos duplicado")
        vistos.add((item["raw"],item["manifesto"]))
        dados=_arquivo_pasta(pasta,item["raw"],MAX_BYTES)
        meta_b=_arquivo_pasta(pasta,item["manifesto"],MAX_MANIFEST)
        total_bytes+=len(dados)+len(meta_b)
        if total_bytes>MAX_LOTE_BYTES:
            raise ErroLoteQuarentenaPTAX("lote acima do limite")
        try:
            meta=json.loads(meta_b.decode("utf-8","strict"))
            prova=validar_amostra_ptax(dados,meta)
        except (ValueError,UnicodeError,TypeError) as exc:
            raise ErroLoteQuarentenaPTAX("item OData/manifesto inválido") from exc
        itens.append((dados,meta,prova))
    resultados=[]
    with savepoint_atomico(db):
        for dados,meta,prova in itens:
            r=receber_amostra_ptax(db,raw=dados,manifesto=meta)
            if r["evento_sha256"]!=prova["evento_sha256"]:
                raise ErroLoteQuarentenaPTAX("inconsistência entre pré-validação e gravação")
            resultados.append(r)
    return {
        "status":"LOTE_PTAX_QUARENTENA_RECEBIDO_SEM_PUBLICACAO",
        "itens_processados":len(resultados),
        "eventos_novos":sum(x["nova_versao"] for x in resultados),
        "boletins_verificados":sum(x["boletins"] for x in resultados),
        "respostas_vazias":sum(x["vazio"] for x in resultados),
        "total_entrada_bytes":total_bytes,
        "eventos_sha256":[x["evento_sha256"] for x in resultados],
        "custo_nuvem_iniciado":False,
        "ledger_operacional_modificado":False,
        "publicavel":False,
    }


def main(argv: list[str] | None = None) -> dict:
    parser=argparse.ArgumentParser(
        description="Receber muitas capturas OData/PTAX na quarentena de uma vez"
    )
    parser.add_argument("--pasta",required=True)
    parser.add_argument("--lote",required=True)
    parser.add_argument("--banco",required=True)
    args=parser.parse_args(argv)
    pasta=Path(args.pasta)
    raw_lote=_arquivo_pasta(pasta,args.lote,MAX_MANIFEST)
    try:
        dados=json.loads(raw_lote.decode("utf-8","strict"))
    except (ValueError,UnicodeError) as exc:
        raise ErroLoteQuarentenaPTAX("JSON do lote inválido") from exc
    banco=Path(args.banco)
    if banco.is_symlink() or banco.exists() and not banco.is_file():
        raise ErroLoteQuarentenaPTAX("destino SQLite inválido")
    with sqlite3.connect(banco) as db:
        db.execute("PRAGMA foreign_keys=ON")
        return importar_lote_ptax_quarentena(
            db,pasta=pasta,lote=dados,
        )


if __name__=="__main__":
    print(json.dumps(main(),ensure_ascii=False,sort_keys=True))
