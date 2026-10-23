#!/usr/bin/env python3
"""Ciclo shadow LOCAL sob demanda, no instante atual de execução.

NÃO é serviço independente de assinatura/tempo. Nenhum forecast é
retrodatado pela CLI. Exige recibos privados fora do SQLite; saída JSON
reconhece se a gravação teve êxito mas o recibo não foi criado.
"""
from __future__ import annotations

import argparse
from datetime import datetime,timezone
import json
import os
from pathlib import Path
import sqlite3
import stat
import sys
from urllib.parse import quote

from nivon.fretes_ciclo_shadow import executar_ciclo_shadow_frete_local
from nivon.fretes_ledger_persistente import ErroLedgerFrete
from nivon.fretes_ofertas_store import ErroStoreOfertaFrete
from nivon.fretes_previsoes_arquivadas import ErroAvaliacaoFrete
from nivon.fretes_recibos_ancora import ErroReciboFrete

CAMPOS_CONFIG=frozenset({
    "arquivo_sqlite","diretorio_recibos",
    "cabeca_ofertas_esperada","cabeca_previsoes_esperada",
    "condicoes","fonte_id","emissor_previsao",
    "emissor_recibo","horizontes_dias",
})
CAMPOS_CONDICOES=frozenset({
    "origem_ibge","destino_ibge","descarga_entity_id",
    "produto","equipamento","regime","pedagio",
})


def _segredo(chave: str) -> bytes:
    texto=os.environ.get(chave,"")
    if not texto or len(texto)<64 or len(texto)%2 or len(texto)>8192:
        raise ValueError("chave não configurada no serviço")
    try:
        chave_bytes=bytes.fromhex(texto)
    except ValueError as exc:
        raise ValueError("formato de chave inválido") from exc
    if len(chave_bytes)<32:
        raise ValueError("chave abaixo do comprimento exigido")
    return chave_bytes


def _privado(arquivo, sufixo, tamanho) -> Path:
    if not isinstance(arquivo,str):
        raise ValueError("arquivo local não informado")
    p=Path(arquivo)
    if (p.is_symlink() or not p.is_file() or p.suffix!=sufixo
            or p.stat().st_size>tamanho
            or not stat.S_ISREG(p.stat().st_mode)
            or p.stat().st_mode&0o077):
        raise ValueError("arquivo deve existir e possuir modo privado 0600")
    return p


def executar(config: dict, *, agora: datetime) -> dict:
    if not isinstance(config,dict) or set(config)!=CAMPOS_CONFIG:
        raise ValueError("configuração de ciclo não canônica")
    econ=config["condicoes"]
    hs=config["horizontes_dias"]
    if (not isinstance(econ,dict) or set(econ)!=CAMPOS_CONDICOES
            or any(type(v) is not str or not v for v in econ.values())
            or not isinstance(hs,list) or not hs
            or any(type(h) is not int or not 1<=h<=365 for h in hs)
            or sorted(set(hs))!=hs):
        raise ValueError("condições econômicas ou horizonte inválidos")
    db=_privado(config["arquivo_sqlite"],".sqlite",100_000_000)
    local=Path(config["diretorio_recibos"])
    if (not local.is_absolute() or not local.is_dir()
            or local.is_symlink() or local.stat().st_mode&0o077):
        raise ValueError("diretório de recibos deve existir e ser privado 0700")
    chave_previsao=_segredo("NIVON_FRETE_PREVISAO_KEY_HEX")
    chave_recibo=_segredo("NIVON_FRETE_RECIBO_KEY_HEX")
    if chave_previsao==chave_recibo:
        raise ValueError("chaves de previsão e recibo não podem coincidir")
    uri="file:"+quote(str(db.resolve()),safe="/")+"?mode=rw"
    with sqlite3.connect(uri,uri=True,timeout=10) as con:
        return executar_ciclo_shadow_frete_local(
            con,recebido_em=agora,
            cabeca_ofertas_esperada=config["cabeca_ofertas_esperada"],
            cabeca_previsoes_esperada=config["cabeca_previsoes_esperada"],
            condicoes=econ,fonte_id=config["fonte_id"],
            emissor_previsao=config["emissor_previsao"],
            chave_previsao=chave_previsao,
            emissor_recibo=config["emissor_recibo"],
            chave_recibo=chave_recibo,
            diretorio_recibos=local,horizontes_dias=tuple(hs),
        )


def main() -> int:
    parser=argparse.ArgumentParser(description="Grava forecasts shadow LOCAL e recibo")
    parser.add_argument("--config",required=True)
    args=parser.parse_args()
    try:
        cfg=_privado(args.config,".json",8192)
        obj=json.loads(cfg.read_text(encoding="utf-8"))
        result=executar(obj,agora=datetime.now(timezone.utc))
    except (OSError,ValueError,TypeError,KeyError,sqlite3.Error,
            ErroAvaliacaoFrete,ErroLedgerFrete,ErroStoreOfertaFrete,
            ErroReciboFrete) as exc:
        print(json.dumps({
            "status":"CICLO_SHADOW_BLOQUEADO",
            "classe":type(exc).__name__,
            "publicavel":False,
        }),file=sys.stderr)
        return 2
    print(json.dumps(result,ensure_ascii=False,sort_keys=True))
    # Retornar falha explícita sem perder a cabeça do banco no stdout.
    return 0 if result["recibo_local_emitido"] else 3


if __name__=="__main__":
    raise SystemExit(main())
