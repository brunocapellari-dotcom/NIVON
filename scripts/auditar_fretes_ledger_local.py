#!/usr/bin/env python3
"""Auditoria OFFLINE read-only de fretes/forecast arquivado.

Uso: PYTHONPATH=src python scripts/auditar_fretes_ledger_local.py --config arquivo.json
A chave HMAC é lida EXCLUSIVAMENTE de NIVON_FRETE_HMAC_KEY_HEX.
Nenhuma coleta, alteração de banco, credencial impressa ou relatório público.
"""
from __future__ import annotations

import argparse
from datetime import datetime
import json
import os
from pathlib import Path
import sqlite3
import sys
from urllib.parse import quote

from nivon.fretes_cobertura_horizontes import auditar_cobertura_horizontes_frete
from nivon.fretes_entrada_jsonl import carregar_ofertas_frete_jsonl
from nivon.fretes_ofertas_store import verificar_store_ofertas_frete
from nivon.fretes_ledger_persistente import (
    ErroLedgerFrete, verificar_ledger_frete, avaliar_ledger_frete,
)
from nivon.fretes_previsoes_arquivadas import ErroAvaliacaoFrete
from nivon.fretes_registros import ErroRegistroFrete


CAMPOS_CONFIG={
    "arquivo_sqlite", "arquivo_ofertas", "cabeca_externa_sha256",
    "as_of", "emissor_esperado", "modelo_versao", "fonte_id",
    "horizontes_dias", "condicoes",
}
CAMPOS_CONFIG_STORE=(CAMPOS_CONFIG-{"arquivo_ofertas"}) | {
    "arquivo_ofertas_sqlite", "cabeca_ofertas_sha256",
}
CAMPOS_CONDICOES={
    "origem_ibge","destino_ibge","descarga_entity_id",
    "produto","equipamento","regime","pedagio",
}


def executar(config: dict, *, segredo_hex: str) -> dict:
    """É apenas interface para dados previamente exportados e autorizados."""
    if not isinstance(config,dict) or set(config) not in (
            CAMPOS_CONFIG,CAMPOS_CONFIG_STORE):
        raise ValueError("configuração incompleta ou mistura de fontes JSONL/SQLite")
    usa_store=set(config)==CAMPOS_CONFIG_STORE
    if (not isinstance(config["condicoes"],dict)
            or set(config["condicoes"])!=CAMPOS_CONDICOES
            or any(not isinstance(v,str) or not v for v in config["condicoes"].values())):
        raise ValueError("condições econômicas incompletas")
    hs=config["horizontes_dias"]
    if (not isinstance(hs,list) or not hs or len(hs)>8
            or any(type(h) is not int or not 1<=h<=365 for h in hs)
            or hs!=sorted(set(hs))):
        raise ValueError("horizontes precisam ser dias corridos ordenados")
    if not isinstance(segredo_hex,str) or len(segredo_hex)<64 or len(segredo_hex)%2:
        raise ValueError("NIVON_FRETE_HMAC_KEY_HEX ausente ou curta")
    try:
        chave=bytes.fromhex(segredo_hex)
    except ValueError as exc:
        raise ValueError("NIVON_FRETE_HMAC_KEY_HEX inválida") from exc
    if len(chave)<32:
        raise ValueError("chave de verificação muito curta")
    asof=datetime.fromisoformat(config["as_of"].replace("Z","+00:00"))
    if asof.tzinfo is None or asof.utcoffset() is None:
        raise ValueError("as_of exige timezone")
    path=Path(config["arquivo_sqlite"])
    if (path.is_symlink() or not path.is_file()
            or path.stat().st_size>100_000_000):
        raise ValueError("SQLite local ausente, link ou excessivo")
    if usa_store:
        p=Path(config["arquivo_ofertas_sqlite"])
        if p.is_symlink() or not p.is_file() or p.stat().st_size>100_000_000:
            raise ValueError("SQLite de ofertas local inválido")
        uri_ofertas="file:"+quote(str(p.resolve()),safe="/")+"?mode=ro"
        with sqlite3.connect(uri_ofertas,uri=True) as con_ofertas:
            con_ofertas.execute("PRAGMA query_only=ON")
            dados=verificar_store_ofertas_frete(
                con_ofertas,
                cabeca_esperada_sha256=config["cabeca_ofertas_sha256"],
            )
            ofertas=dados["ofertas"]
        cabeca_ofertas=dados["cabeca_sha256"]
    else:
        ofertas=carregar_ofertas_frete_jsonl(config["arquivo_ofertas"])
        cabeca_ofertas=None
    args=dict(config["condicoes"])
    cobertura=auditar_cobertura_horizontes_frete(
        ofertas,as_of=asof,horizontes_dias=tuple(hs),**args,
    )
    uri="file:"+quote(str(path.resolve()),safe="/")+ "?mode=ro"
    with sqlite3.connect(uri,uri=True) as con:
        con.execute("PRAGMA query_only=ON")
        ver=verificar_ledger_frete(
            con,cabeca_esperada_sha256=config["cabeca_externa_sha256"],
            chave_verificacao=chave,emissor_esperado=config["emissor_esperado"],
        )
        metricas={}
        for h in hs:
            try:
                m=avaliar_ledger_frete(
                    con,ofertas,
                    cabeca_esperada_sha256=config["cabeca_externa_sha256"],
                    chave_verificacao=chave,emissor_esperado=config["emissor_esperado"],
                    as_of=asof,modelo_versao=config["modelo_versao"],
                    fonte_id=config["fonte_id"],horizonte_dias_corridos=h,
                    **args,
                )
            except ErroAvaliacaoFrete as exc:
                # Valor bloqueado continua visível; não se deduz "skill".
                metricas[str(h)]={"status":"BLOQUEADO_SEM_VALIDACAO_COMPLETA",
                                 "motivo":str(exc),"publicavel":False}
            else:
                metricas[str(h)]={
                    "status":m["status"],"n":m["n_previsoes_declaradas"],
                    "mae":m["mae_brl_t"],"rmse":m["rmse_brl_t"],
                    "mae_baseline_zero":m["mae_baseline_zero_brl_t"],
                    "rmse_baseline_zero":m["rmse_baseline_zero_brl_t"],
                    "ganho_mae_baseline":m["ganho_mae_vs_zero"],
                    "ganho_rmse_baseline":m["ganho_rmse_vs_zero"],
                    "habilitado_para_producao":False,"publicavel":False,
                }
    return {
        "status":"RELATORIO_OFFLINE_DADOS_DECLARADOS_NAO_HOMOLOGADOS",
        "cabeca_ledger_conferida":ver["cabeca_sha256"],
        "registros_ledger":ver["quantidade"],
        "origem_ofertas":"SQLITE_STORE" if usa_store else "JSONL_EXPORTADO",
        "cabeca_store_ofertas_conferida":cabeca_ofertas,
        "dias_com_ofertas":cobertura["dias_observados"],
        "cobertura_horizontes":[{
            "dias":x["horizonte_dias_corridos"],
            "origens_comparaveis":x["origens_com_pares_comparaveis"],
            "origens_sem_alvo":x["origens_sem_alvo_observado"],
            "status":x["status"],
        } for x in cobertura["horizontes"]],
        "avaliacoes":metricas,
        "credenciais_ou_chaves_expostas":False,
        "dados_originais_autenticados":False,
        "direitos_de_uso_homologados":False,
        "prova_temporal_externa_autenticada":False,
        "previsoes_operacionais_homologadas":False,
        "publicavel":False,
    }


def main() -> int:
    parser=argparse.ArgumentParser(
        description="Auditoria somente-leitura de forecasts de fretes anunciados"
    )
    parser.add_argument("--config",required=True,help="JSON local sem credenciais")
    ns=parser.parse_args()
    try:
        p=Path(ns.config)
        if p.is_symlink() or not p.is_file() or p.stat().st_size>8192:
            raise ValueError("arquivo de configuração local inválido")
        config=json.loads(p.read_text(encoding="utf-8"))
        resultado=executar(
            config,segredo_hex=os.environ.get("NIVON_FRETE_HMAC_KEY_HEX","")
        )
    except (ValueError,TypeError,KeyError,OSError,sqlite3.DatabaseError,
            ErroRegistroFrete,ErroAvaliacaoFrete,ErroLedgerFrete) as exc:
        print(json.dumps({"status":"BLOQUEADO","tipo_erro":type(exc).__name__,
                          "publicavel":False},ensure_ascii=False),file=sys.stderr)
        return 2
    print(json.dumps(resultado,sort_keys=True,ensure_ascii=False,indent=2))
    return 0


if __name__=="__main__":
    raise SystemExit(main())
