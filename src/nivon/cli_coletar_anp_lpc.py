"""Entrada operacional do lote ANP/LPC, sem agendamento nem deploy.

Uso real explícito:
 python -m nivon.cli_coletar_anp_lpc --modo rede --ano 2026 --db PATH --raw-dir PATH
Uso local para arquivos já obtidos:
 python -m nivon.cli_coletar_anp_lpc --modo arquivos --ano 2026 \
   --indice PATH --pasta-arquivos PATH --db PATH --raw-dir PATH
Consulta de tendência preliminar (não publicável):
 python -m nivon.cli_coletar_anp_lpc --modo consulta --db PATH \
   --municipio SINOP --produto 'DIESEL S10'
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import sqlite3
import sys
from urllib.parse import urlsplit

from .anp_indice_lpc import descobrir_semanas_lpc
from .anp_lpc_coletor_real import coletar_lpc, ErroColetaANP
from .anp_lpc_staging_real import iniciar_staging, tendencia_diesel_preliminar


def _db_seguro(path: Path) -> sqlite3.Connection:
    if path.is_symlink() or not path.parent.is_dir():
        raise ErroColetaANP("diretório DB inexistente ou caminho simbólico inseguro")
    if path.exists() and not path.is_file():
        raise ErroColetaANP("arquivo DB inválido")
    conn = sqlite3.connect(str(path), timeout=15)
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def _local_files(index_html: bytes, pasta: Path, *, ano: int, limite: int):
    if pasta.is_symlink() or not pasta.is_dir():
        raise ErroColetaANP("pasta de arquivos local ausente/insegura")
    oficial = descobrir_semanas_lpc(index_html, ano=ano)
    weeks = sorted(
        oficial["semanas"], key=lambda x: x["semana_inicio"], reverse=True
    )[:limite]
    files = {}
    for entry in weeks:
        name = urlsplit(entry["url_pagina"]).path.rsplit("/", 1)[-1]
        path = pasta / name
        if path.is_symlink() or not path.is_file() or not path.resolve().is_relative_to(pasta.resolve()):
            raise ErroColetaANP(f"arquivo XLSX local ausente ou simbólico: {name}")
        if not 100 <= path.stat().st_size <= 14_000_000:
            raise ErroColetaANP("arquivo XLSX local não atende limites")
        files[entry["url_pagina"]] = path.read_bytes()
    return files


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Lote ANP/LPC isolado, não comercial")
    parser.add_argument("--modo", choices=["rede", "arquivos", "consulta"], required=True)
    parser.add_argument("--db", type=Path, required=True)
    parser.add_argument("--raw-dir", type=Path)
    parser.add_argument("--ano", type=int, default=datetime.now(timezone.utc).year)
    parser.add_argument("--ultimas", type=int, default=3)
    parser.add_argument("--indice", type=Path)
    parser.add_argument("--pasta-arquivos", type=Path)
    parser.add_argument("--municipio", type=str)
    parser.add_argument("--produto", choices=["DIESEL", "DIESEL S10"])
    parser.add_argument("--as-of", type=str)
    args = parser.parse_args(argv)
    try:
        if args.modo == "rede" and (
            args.raw_dir is None or args.indice is not None
            or args.pasta_arquivos is not None
        ):
            raise ErroColetaANP("coleta de rede requer --raw-dir e não aceita arquivo local")
        if args.modo == "arquivos" and (
            args.indice is None or args.pasta_arquivos is None
        ):
            raise ErroColetaANP("modo arquivos requer --indice e --pasta-arquivos")
        if args.modo == "consulta" and (
            not args.municipio or args.produto is None
        ):
            raise ErroColetaANP("consulta exige --municipio e --produto")
        if args.raw_dir is not None and (
            args.raw_dir.is_symlink() or not args.raw_dir.is_dir()
        ):
            raise ErroColetaANP("pasta RAW deve existir e não pode ser simbólica")
        with _db_seguro(args.db) as db:
            iniciar_staging(db)
            if args.modo == "consulta":
                data = tendencia_diesel_preliminar(
                    db, municipio=args.municipio.upper().strip(),
                    produto=args.produto,
                    as_of=args.as_of or datetime.now(timezone.utc).isoformat(),
                )
                code = 0
            else:
                options = {}
                if args.modo == "arquivos":
                    if (args.indice.is_symlink() or not args.indice.is_file()
                            or not 100 <= args.indice.stat().st_size <= 4_000_000):
                        raise ErroColetaANP("arquivo de índice local inválido")
                    indice = args.indice.read_bytes()
                    options = {
                        "indice_bytes": indice,
                        "arquivos_locais": _local_files(
                            indice, args.pasta_arquivos,
                            ano=args.ano, limite=args.ultimas,
                        ),
                    }
                data = coletar_lpc(
                    db, ano=args.ano, limite_semanas=args.ultimas,
                    raw_dir=args.raw_dir, **options
                )
                code = 0 if data["status"] == "LOTE_COMPLETO" else 2
        print(json.dumps(data, ensure_ascii=False, sort_keys=True, indent=2))
        return code
    except (OSError, ValueError, PermissionError, sqlite3.Error) as exc:
        print(json.dumps({
            "status": "FALHA_CONTROLADA", "tipo": type(exc).__name__,
            "motivo": str(exc)[:400], "publicavel": False,
        }, ensure_ascii=False), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
