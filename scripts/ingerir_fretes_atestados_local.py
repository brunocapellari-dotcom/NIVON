#!/usr/bin/env python3
"""Ingestão OFFLINE por arquivo privado de envelopes já atestados pelo WhatsApp AI.

O arquivo contém RAW codificado em base64; deve ter permissão local 0600.
O processo verifica HMAC de direitos/resolução e vínculo do RAW e NÃO
persiste o conteúdo original; não acessa WhatsApp, Drive, rede ou nuvem.
Só processa recepção recente, e requer um SQLite já inicializado.
"""
from __future__ import annotations

import argparse
import base64
import binascii
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import sqlite3
import stat
import sys
from urllib.parse import quote

from nivon.fretes_ingestao_atestada import ingerir_lote_whatsapp_atestado
from nivon.fretes_ofertas_store import ErroStoreOfertaFrete


CAMPOS_CONFIG=frozenset({
    "arquivo_ofertas_sqlite","arquivo_envelopes_jsonl",
    "cabeca_anterior_sha256","emissores_atestacao",
})
CAMPOS_ENVELOPE=frozenset({
    "evento","resolucao","autorizacao","data_coleta","raw_base64",
})


def _arquivo_privado(path: object, *, extension: str, limit: int) -> Path:
    if not isinstance(path,str) or not path:
        raise ValueError("caminho privado local obrigatório")
    p=Path(path)
    if (p.suffix!=extension or p.is_symlink() or not p.is_file()
            or p.stat().st_size > limit or not stat.S_ISREG(p.stat().st_mode)
            or p.stat().st_mode & 0o077):
        raise ValueError("arquivo não regular, indisponível, exposto ou excessivo")
    return p


def _chave(variavel: str) -> bytes:
    value=os.environ.get(variavel,"")
    if not value or len(value)%2 or len(value)>8192:
        raise ValueError("chave HMAC do runtime ausente")
    try:
        key=bytes.fromhex(value)
    except ValueError as exc:
        raise ValueError("chave HMAC do runtime inválida") from exc
    if len(key)<32:
        raise ValueError("chave HMAC do runtime insuficiente")
    return key


def _envelopes(path: Path) -> list[dict]:
    result=[]
    with path.open("r",encoding="utf-8") as fp:
        for n,line in enumerate(fp,1):
            if n>500 or not line.strip() or len(line)>300_000:
                raise ValueError("envelopes excessivos ou linha inválida")
            def _invalid_constant(value):
                raise ValueError("valor JSON não-finito")
            obj=json.loads(line,parse_constant=_invalid_constant)
            if not isinstance(obj,dict) or set(obj)!=CAMPOS_ENVELOPE:
                raise ValueError("envelope não corresponde ao contrato")
            if not isinstance(obj["raw_base64"],str):
                raise ValueError("RAW base64 inválido")
            try:
                raw=base64.b64decode(obj["raw_base64"],validate=True)
            except (binascii.Error,ValueError) as exc:
                raise ValueError("RAW base64 malformado") from exc
            dt=datetime.fromisoformat(obj["data_coleta"].replace("Z","+00:00"))
            if dt.tzinfo is None or dt.utcoffset() is None:
                raise ValueError("coleta sem timezone")
            result.append({
                "evento":obj["evento"],"resolucao":obj["resolucao"],
                "autorizacao":obj["autorizacao"],
                "data_coleta":dt,"raw_bytes":raw,
            })
    if not result:
        raise ValueError("arquivo de envelopes vazio")
    return result


def executar(config: dict, *, recebido_em: datetime) -> dict:
    """Uma importação transacional; o operador armazena a cabeça fora do DB."""
    if not isinstance(config,dict) or set(config)!=CAMPOS_CONFIG:
        raise ValueError("configuração da ingestão incompatível")
    emissores=config["emissores_atestacao"]
    if (not isinstance(emissores,dict) or set(emissores)!={"DIREITOS","RESOLUCAO"}
            or any(not isinstance(v,str) or not v for v in emissores.values())
            or emissores["DIREITOS"]==emissores["RESOLUCAO"]):
        raise ValueError("atestadores independentes não identificados")
    db=_arquivo_privado(
        config["arquivo_ofertas_sqlite"],extension=".sqlite",limit=100_000_000
    )
    arquivo=_arquivo_privado(
        config["arquivo_envelopes_jsonl"],extension=".jsonl",limit=50_000_000
    )
    chaves={
        "DIREITOS":_chave("NIVON_FRETE_DIREITOS_KEY_HEX"),
        "RESOLUCAO":_chave("NIVON_FRETE_RESOLUCAO_KEY_HEX"),
    }
    pseudo=_chave("NIVON_FRETE_PSEUDO_KEY_HEX")
    if pseudo in chaves.values() or chaves["DIREITOS"]==chaves["RESOLUCAO"]:
        raise ValueError("chaves de direitos, resolução e pseudônimo devem ser diferentes")
    envelopes=_envelopes(arquivo)
    uri="file:"+quote(str(db.resolve()),safe="/")+"?mode=rw"
    with sqlite3.connect(uri,uri=True,timeout=10) as con:
        result=ingerir_lote_whatsapp_atestado(
            con,envelopes,
            cabeca_anterior_sha256=config["cabeca_anterior_sha256"],
            recebido_em=recebido_em,
            chave_pseudonimizacao=pseudo,chaves_atestacao=chaves,
            emissores_atestacao=emissores,
        )
    return {
        "status":result["status"],
        "publicacoes_recebidas":result["publicacoes_recebidas"],
        "registros_individuais_inseridos":result["registros_individuais_inseridos"],
        "republicacoes_idempotentes":result["republicacoes_idempotentes"],
        "total_store":result["total_store"],
        "nova_cabeca_sha256":result["cabeca_sha256"],
        "novo_recibo_externo_gerado":False,
        "raw_armazenado_neste_store":False,
        "coleta_whatsapp_live_conectada":False,
        "publicavel":False,
    }


def main() -> int:
    parser=argparse.ArgumentParser(
        description="Importar arquivo PRIVADO de anúncios previamente atestados"
    )
    parser.add_argument("--config",required=True)
    args=parser.parse_args()
    try:
        p=_arquivo_privado(args.config,extension=".json",limit=8192)
        doc=json.loads(p.read_text(encoding="utf-8"))
        result=executar(doc,recebido_em=datetime.now(timezone.utc))
    except (ValueError,TypeError,KeyError,OSError,sqlite3.Error,
            ErroStoreOfertaFrete) as exc:
        # Não imprimir payloads de anúncios, nomes, tokens, caminhos ou chaves.
        print(json.dumps({
            "status":"INGESTAO_BLOQUEADA",
            "classe":type(exc).__name__,
            "publicavel":False,
        }),file=sys.stderr)
        return 2
    print(json.dumps(result,sort_keys=True,ensure_ascii=False))
    return 0


if __name__=="__main__":
    raise SystemExit(main())
