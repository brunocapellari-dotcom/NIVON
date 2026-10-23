"""CLI para arquivar estágio antes do MERGE ou recuperar lote pelo GCS.

A autorização para alteração real é externa: IAM/WIF, permissão de fonte
e orçamento devem estar aprovados. Plano (sem --executar) nunca chama GCP.
"""
from __future__ import annotations

import argparse
import json
import os

from nivon.lote_cloud_recuperavel import arquivar_stage, preparar_lote, reprocessar_manifesto


def main(argv=None):
    p=argparse.ArgumentParser(description="NIVON: stage GCS recuperável / replay BQ")
    p.add_argument("--fase", required=True, choices=("arquivar", "replay"))
    p.add_argument("--banco", default="data/nivon/fontes_reais.sqlite")
    p.add_argument("--arquivo", default="data/nivon/staging_fontes_reais.jsonl")
    p.add_argument("--projeto", required=True)
    p.add_argument("--dataset", required=True)
    p.add_argument("--bucket", required=True)
    p.add_argument("--manifesto-sha")
    p.add_argument("--executar", action="store_true")
    args=p.parse_args(argv)
    if args.executar and (os.getenv("NIVON_ZERO_COST_BQ_APPROVED")!="true"
                         or os.getenv("NIVON_RAW_ARCHIVE_APPROVED")!="true"):
        raise PermissionError("operação GCP sem gate de custo e arquivamento")
    comuns=dict(bucket=args.bucket,projeto=args.projeto,dataset=args.dataset)
    if args.fase=="arquivar":
        if args.manifesto_sha:
            p.error("manifesto-sha não se aplica ao arquivamento")
        if not args.executar:
            plano=preparar_lote(banco=args.banco,arquivo_jsonl=args.arquivo,**comuns)
            resultado={"executado":False,"linhas":plano["plano"]["linhas"],
                       "manifesto_sha256":plano["manifesto_sha256"]}
        else:
            resultado=arquivar_stage(banco=args.banco,arquivo_jsonl=args.arquivo,
                                    executar=True,**comuns)
    else:
        if not args.manifesto_sha:
            p.error("replay exige --manifesto-sha")
        resultado=reprocessar_manifesto(manifesto_sha256=args.manifesto_sha,
                                         executar=args.executar,**comuns)
    print(json.dumps(resultado,ensure_ascii=False,indent=2))
    return 0


if __name__=="__main__":
    raise SystemExit(main())
