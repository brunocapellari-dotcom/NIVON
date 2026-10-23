#!/usr/bin/env python3
"""Recupera RECIBO, nunca forecasts, após crash de emissão shadow local.

Requer checkpoint anterior obtido fora do SQLite; consulta banco read-only.
Chaves recebidas só pelo ambiente. Relógio da recuperação = UTC corrente,
sem opção de retrodatação por CLI. NÃO é serviço externo/WORM.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import sqlite3
import stat
import sys
from urllib.parse import quote

from nivon.fretes_recuperacao_poscommit import (
    recuperar_recibo_poscommit_frete, ErroRecuperacaoFrete,
)

CAMPOS=frozenset({
    "arquivo_sqlite","cabeca_previsoes_anterior_sha256",
    "quantidade_previsoes_anterior","cabeca_ofertas_sha256",
    "condicoes","fonte_id","emissor_previsao","emissor_recibo",
    "diretorio_recibos","horizontes_dias",
})
ECON=frozenset({
    "origem_ibge","destino_ibge","descarga_entity_id",
    "produto","equipamento","regime","pedagio",
})


def _arquivo_seguro(v: object, extensao: str, limite: int) -> Path:
    if not isinstance(v,str) or not v:
        raise ValueError("arquivo local não informado")
    p=Path(v)
    if (not p.is_file() or p.is_symlink() or p.suffix!=extensao
            or not stat.S_ISREG(p.stat().st_mode)
            or p.stat().st_mode & 0o077 or p.stat().st_size>limite):
        raise ValueError("arquivo local inseguro, ausente ou excessivo")
    return p


def _chave_env(var: str) -> bytes:
    txt=os.environ.get(var,"")
    if len(txt)<64 or len(txt)>8192 or len(txt)%2:
        raise ValueError("chave HMAC não configurada")
    try:
        chave=bytes.fromhex(txt)
    except ValueError as exc:
        raise ValueError("chave HMAC com formato inválido") from exc
    if len(chave)<32:
        raise ValueError("chave HMAC não confiável")
    return chave


def executar(config: dict, *, agora: datetime) -> dict:
    if not isinstance(config,dict) or set(config)!=CAMPOS:
        raise ValueError("configuração de recuperação incompatível")
    econ=config["condicoes"]
    hs=config["horizontes_dias"]
    if (not isinstance(econ,dict) or set(econ)!=ECON
            or any(type(v) is not str or not v for v in econ.values())
            or not isinstance(hs,list) or not hs or len(hs)>8
            or any(type(x) is not int or x<1 or x>365 for x in hs)
            or hs!=sorted(set(hs))):
        raise ValueError("rota, condições ou horizontes inválidos")
    db=_arquivo_seguro(config["arquivo_sqlite"],".sqlite",100_000_000)
    pasta=Path(config["diretorio_recibos"])
    if (not pasta.is_absolute() or pasta.is_symlink() or not pasta.is_dir()
            or pasta.stat().st_mode & 0o077):
        raise ValueError("diretório de recibos privado obrigatório")
    chave_prev=_chave_env("NIVON_FRETE_PREVISAO_KEY_HEX")
    chave_recibo=_chave_env("NIVON_FRETE_RECIBO_KEY_HEX")
    if chave_prev==chave_recibo:
        raise ValueError("chaves distintas exigidas")
    uri="file:"+quote(str(db.resolve()),safe="/")+"?mode=ro"
    with sqlite3.connect(uri,uri=True) as con:
        con.execute("PRAGMA query_only=ON")
        return recuperar_recibo_poscommit_frete(
            con,
            cabeca_previsoes_anterior_sha256=config["cabeca_previsoes_anterior_sha256"],
            quantidade_previsoes_anterior=config["quantidade_previsoes_anterior"],
            cabeca_ofertas_sha256=config["cabeca_ofertas_sha256"],
            condicoes=econ,fonte_id=config["fonte_id"],
            emissor_previsao=config["emissor_previsao"],
            chave_previsao=chave_prev,
            emissor_recibo=config["emissor_recibo"],
            chave_recibo=chave_recibo,
            instante_recuperacao=agora,
            diretorio_recibos=pasta,horizontes_dias=tuple(hs),
        )


def main() -> int:
    p=argparse.ArgumentParser(description="Recuperar recibo pós-commit, SEM reemitir previsão")
    p.add_argument("--config",required=True)
    args=p.parse_args()
    try:
        cfg=_arquivo_seguro(args.config,".json",8192)
        data=json.loads(cfg.read_text(encoding="utf-8"))
        result=executar(data,agora=datetime.now(timezone.utc))
    except (OSError,ValueError,TypeError,KeyError,sqlite3.Error,
            ErroRecuperacaoFrete) as exc:
        # Não publicar IDs de estabelecimento, chaves, payloads ou paths.
        print(json.dumps({
            "status":"RECUPERACAO_BLOQUEADA",
            "classe":type(exc).__name__,
            "publicavel":False,
        }),file=sys.stderr)
        return 2
    print(json.dumps(result,ensure_ascii=False,sort_keys=True))
    return 0


if __name__=="__main__":
    raise SystemExit(main())
