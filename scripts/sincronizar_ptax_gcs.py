"""Sincronizar quarentena PTAX no GCS por comando explícito.

Por padrão APENAS planeja objetos e exibe hashes; não acessa GCS,
não cria bucket, não ativa cobrança ou serviço recorrente.
Uso real requer permissão de upload + referências de direito/orçamento
+ Google Cloud ADC já configurada. Lote limitado a dez eventos.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sqlite3

from nivon.ptax_google_cloud import preparar_objetos_gcs_ptax
from nivon.ptax_quarentena_coleta import listar_amostras_ptax
from nivon.ptax_sincronizacao_gcs import sincronizar_pacote_ptax_gcs


def main(argv: list[str] | None = None) -> dict:
    parser = argparse.ArgumentParser(
        description="Arquivar PTAX em GCS com dry-run por padrão e sem overwrite"
    )
    parser.add_argument("--banco", required=True)
    parser.add_argument("--bucket", required=True)
    parser.add_argument("--prefixo", default="nivon/ptax/quarentena/v1")
    parser.add_argument("--evento-sha")
    parser.add_argument("--max-eventos", type=int, default=5)
    parser.add_argument("--confirmar-upload", action="store_true")
    parser.add_argument("--referencia-direitos")
    parser.add_argument("--referencia-custo")
    args = parser.parse_args(argv)
    if not 1 <= args.max_eventos <= 10:
        raise ValueError("máximo de dez eventos por execução")
    f = Path(args.banco)
    if f.is_symlink() or not f.is_file():
        raise ValueError("banco de quarentena existente obrigatório")
    if args.confirmar_upload and (
        not args.referencia_direitos or not args.referencia_custo
    ):
        raise PermissionError("direitos e orçamento exigidos antes do upload")
    with sqlite3.connect(f) as db:
        db.execute("PRAGMA foreign_keys=ON")
        registros = listar_amostras_ptax(db, limite=1000)
        if args.evento_sha:
            ids = [args.evento_sha]
            if not any(x["evento_sha256"] == args.evento_sha for x in registros):
                raise ValueError("evento não pertence à quarentena")
        else:
            # A opção padrão só examina os primeiros eventos; não faz
            # varredura de todo o arquivo de capturas em cada execução.
            ids = [x["evento_sha256"] for x in registros[:args.max_eventos]]
        if len(ids) > args.max_eventos:
            raise ValueError("evento(s) acima do limite aprovado")
        saidas = []
        for ident in ids:
            pacote = preparar_objetos_gcs_ptax(
                db, evento_sha256=ident,
                bucket=args.bucket, prefixo=args.prefixo,
            )
            if args.confirmar_upload:
                result = sincronizar_pacote_ptax_gcs(
                    pacote, permitir_upload=True,
                    referencia_direitos=args.referencia_direitos,
                    referencia_custo=args.referencia_custo,
                )
                saidas.append({
                    "evento_sha256":ident,
                    "status":result["status"],
                    "objetos_novos":result["objetos_novos"],
                    "total_conferidos":result["total_conferidos"],
                })
            else:
                saidas.append({
                    "evento_sha256":ident,
                    "status":"PLANEJADO_SEM_ENVIO",
                    "objetos":[{
                        "chave":o["chave"],"sha256":o["sha256"],
                        "bytes":len(o["bytes"]),
                    } for o in pacote["objetos"]],
                })
    return {
        "status": ("SINCRONIZACAO_GCS_RECONCILIADA_SEM_PUBLICACAO"
                   if args.confirmar_upload else "DRY_RUN_SEM_CLOUD"),
        "eventos":saidas,
        "total_eventos":len(saidas),
        "upload_executado":bool(args.confirmar_upload and saidas),
        "publicavel":False,
    }


if __name__ == "__main__":
    print(json.dumps(main(),ensure_ascii=False,sort_keys=True))
