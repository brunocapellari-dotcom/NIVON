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
from contextlib import closing
from datetime import date, datetime, timezone
import json
from pathlib import Path
import sqlite3
import sys
from urllib.parse import urlsplit

from .anp_indice_lpc import descobrir_semanas_lpc
from .anp_lpc_coletor_real import coletar_lpc, ErroColetaANP
from .anp_lpc_staging_real import (iniciar_staging, tendencia_diesel_preliminar,
    painel_qualidade_lpc, auditar_arquivos_origem_lpc)
from .anp_lpc_gcs import exportar_lpc_staging_gcs
from .anp_lpc_ciclo_gcs import executar_ciclo_lpc_gcs


def _db_seguro(path: Path) -> sqlite3.Connection:
    if path.is_symlink() or not path.parent.is_dir():
        raise ErroColetaANP("diretório DB inexistente ou caminho simbólico inseguro")
    if path.exists() and not path.is_file():
        raise ErroColetaANP("arquivo DB inválido")
    conn = sqlite3.connect(str(path), timeout=15)
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def _local_files(
    index_html: bytes, pasta: Path, *, ano: int, limite: int,
    desde: str | None = None, ate: str | None = None,
):
    if pasta.is_symlink() or not pasta.is_dir():
        raise ErroColetaANP("pasta de arquivos local ausente/insegura")
    oficial = descobrir_semanas_lpc(index_html, ano=ano)
    weeks = sorted(
        oficial["semanas"], key=lambda x: x["semana_inicio"], reverse=True
    )
    if desde:
        start = date.fromisoformat(desde)
        weeks = [x for x in weeks if date.fromisoformat(x["semana_inicio"]) >= start]
    if ate:
        end = date.fromisoformat(ate)
        weeks = [x for x in weeks if date.fromisoformat(x["semana_fim"]) <= end]
    weeks = weeks[:limite]
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
    parser.add_argument("--modo", choices=["rede", "arquivos", "consulta", "status", "integridade", "gcs", "ciclo-gcs"], required=True)
    parser.add_argument("--db", type=Path)
    parser.add_argument("--raw-dir", type=Path)
    parser.add_argument("--ano", type=int, default=datetime.now(timezone.utc).year)
    parser.add_argument("--ultimas", type=int, default=3)
    parser.add_argument("--desde", help="Backfill: início mínimo da semana YYYY-MM-DD")
    parser.add_argument("--ate", help="Backfill: fim máximo da semana YYYY-MM-DD")
    parser.add_argument("--indice", type=Path)
    parser.add_argument("--pasta-arquivos", type=Path)
    parser.add_argument("--municipio", type=str)
    parser.add_argument("--produto", choices=["DIESEL", "DIESEL S10"])
    parser.add_argument("--as-of", type=str)
    parser.add_argument("--bucket", help="Bucket GCS privado já existente")
    parser.add_argument("--prefixo", default="nivon/anp/lpc/v1")
    args = parser.parse_args(argv)
    try:
        if args.modo != "ciclo-gcs" and args.db is None:
            raise ErroColetaANP("modo selecionado exige --db")
        if args.modo == "ciclo-gcs" and (
            not args.bucket or args.db is not None or args.raw_dir is not None
            or args.indice is not None or args.pasta_arquivos is not None
        ):
            raise ErroColetaANP(
                "ciclo-gcs exige --bucket e usa estado temporário/recuperado"
            )
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
        if args.modo == "integridade" and args.raw_dir is None:
            raise ErroColetaANP("auditoria de integridade exige --raw-dir")
        if args.modo == "gcs" and (args.raw_dir is None or not args.bucket):
            raise ErroColetaANP("exportação GCS exige --bucket e --raw-dir")
        if args.raw_dir is not None and (
            args.raw_dir.is_symlink() or not args.raw_dir.is_dir()
        ):
            raise ErroColetaANP("pasta RAW deve existir e não pode ser simbólica")
        if args.modo == "ciclo-gcs":
            try:
                from google.cloud import storage
            except ImportError as exc:
                raise ErroColetaANP(
                    "biblioteca opcional google-cloud-storage necessária"
                ) from exc
            client = storage.Client()
            bucket = client.bucket(args.bucket)
            bucket.reload()
            data = executar_ciclo_lpc_gcs(
                bucket=bucket, ano=args.ano, limite_semanas=args.ultimas,
                prefixo=args.prefixo, semana_desde=args.desde,
                semana_ate=args.ate,
            )
            print(json.dumps(data, ensure_ascii=False, sort_keys=True, indent=2))
            return 0 if data["status"] == "CICLO_GCS_COMPLETO" else 2
        with closing(_db_seguro(args.db)) as db:
            iniciar_staging(db)
            if args.modo == "status":
                data = painel_qualidade_lpc(
                    db, as_of=args.as_of or datetime.now(timezone.utc).isoformat())
                code = 0
            elif args.modo == "integridade":
                data = auditar_arquivos_origem_lpc(
                    db, raiz_raw=str(args.raw_dir),
                    as_of=args.as_of or datetime.now(timezone.utc).isoformat(),
                )
                code = 0 if data["status"] == "RAW_VERIFICADO_LOCALMENTE" else 2
            elif args.modo == "gcs":
                # Nunca criar bucket/credenciais/billing implicitamente.
                try:
                    from google.cloud import storage
                except ImportError as exc:
                    raise ErroColetaANP(
                        "biblioteca opcional google-cloud-storage necessária"
                    ) from exc
                client=storage.Client()
                bucket=client.bucket(args.bucket)
                bucket.reload()  # exige bucket existente e identidade ADC
                data=exportar_lpc_staging_gcs(
                    db, raiz_raw=str(args.raw_dir), bucket=bucket,
                    as_of=args.as_of or datetime.now(timezone.utc).isoformat(),
                    prefixo=args.prefixo,
                )
                code=0
            elif args.modo == "consulta":
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
                            desde=args.desde, ate=args.ate,
                        ),
                    }
                data = coletar_lpc(
                    db, ano=args.ano, limite_semanas=args.ultimas,
                    raw_dir=args.raw_dir,
                    semana_desde=args.desde, semana_ate=args.ate,
                    **options
                )
                data["qualidade_staging"] = painel_qualidade_lpc(
                    db, as_of=datetime.now(timezone.utc).isoformat())
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
