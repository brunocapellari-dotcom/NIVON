"""CLI somente leitura: workflows GitHub e plano SQLite -> PostgreSQL NIVON.

Sem acesso a Github Actions, GCP, banco remoto, Cloud API ou WhatsApp.
Exige path local explicitamente autorizado; imprime apenas dados agregados.
"""
from __future__ import annotations

import argparse
import json
import sqlite3
import sys

from nivon.auditoria_workflows_operacionais import analisar_diretorio
from nivon.plano_transicao_outbox_postgres import auditar_arquivo_sqlite


def executar(argv=None) -> dict:
    p=argparse.ArgumentParser(description="NIVON R12: auditoria offline de fontes e outbox")
    p.add_argument("--workflows-dir",help="pasta local YAML; scripts não são executados")
    p.add_argument("--banco",help="SQLite existente; leitura somente")
    p.add_argument("--ddl-postgres",help="DDL versionado, somente leitura")
    args=p.parse_args(argv)
    if not args.workflows_dir and not args.banco:
        p.error("informe --workflows-dir e/ou --banco + --ddl-postgres")
    if bool(args.banco)!=bool(args.ddl_postgres):
        p.error("banco e DDL precisam ser passados juntos")
    out={"modo":"AUDITORIA_SEM_REDE","envios_executados":0,
         "escritas_em_banco":0,"operacao_autorizada":False}
    if args.workflows_dir:
        out["workflows"]=analisar_diretorio(args.workflows_dir)
    if args.banco:
        out["transicao"]=auditar_arquivo_sqlite(
            sqlite_path=args.banco,ddl_path=args.ddl_postgres)
    return out


def main(argv=None) -> int:
    try:
        out=executar(argv)
    except (ValueError,OSError,sqlite3.DatabaseError,UnicodeError):
        # Não logar endereços completos, SQL, contas, tokens ou HMACs em erros.
        print(json.dumps({"resultado":"FALHA_FECHADA","sem_operacao":True}),
              file=sys.stderr)
        return 2
    print(json.dumps(out,ensure_ascii=False,sort_keys=True))
    return 0


if __name__=="__main__":
    raise SystemExit(main())
