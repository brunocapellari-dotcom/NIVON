"""Execução offline de ZIPs ANTAQ autorizados sem depender de rede.

Exemplo:
  PYTHONPATH=src python scripts/importar_antaq_historico.py \
    --ano 2024 --anual ../dados/2024.zip --mercadorias ../dados/Mercadoria.zip \
    --banco ../dados/nivon_antaq.sqlite --coletado-em 2026-10-19T22:00:00-03:00
"""
from __future__ import annotations

import argparse
import json
import sqlite3
from pathlib import Path

from nivon.antaq_historico_offline import MAX_ZIP_BYTES, importar_arquivos


def _ler_zip(path: str) -> bytes:
    p=Path(path)
    if p.is_symlink() or not p.is_file() or not 30 <= p.stat().st_size <= MAX_ZIP_BYTES:
        raise ValueError("ZIP ausente, excessivo, pequeno demais ou symlink")
    return p.read_bytes()


def executar(args: argparse.Namespace) -> dict:
    db=Path(args.banco)
    if db.is_symlink() or not db.parent.is_dir() or db.suffix!=".sqlite":
        raise ValueError("destino SQLite inválido; diretório deve existir")
    anual=_ler_zip(args.anual)
    merc=_ler_zip(args.mercadorias)
    with sqlite3.connect(str(db)) as conn:
        return importar_arquivos(
            anual, merc, ano=args.ano, coletado_em=args.coletado_em, conexao=conn
        )


def main(argv: list[str] | None = None) -> int:
    parser=argparse.ArgumentParser(description="Importar ZIPs ANTAQ autorizados em SQLite")
    parser.add_argument("--ano",type=int,required=True)
    parser.add_argument("--anual",required=True)
    parser.add_argument("--mercadorias",required=True)
    parser.add_argument("--banco",required=True)
    parser.add_argument("--coletado-em",required=True)
    opts=parser.parse_args(argv)
    r=executar(opts)
    print(json.dumps(r,ensure_ascii=False,sort_keys=True))
    return 0


if __name__=="__main__":
    raise SystemExit(main())
