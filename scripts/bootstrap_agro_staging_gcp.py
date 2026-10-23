"""NIVON: validar/criar apenas tabela agro_publicacoes_staging (opt-in)."""
from __future__ import annotations

import argparse
import json
import os
from nivon.agro_staging_bigquery import verificar_ou_criar_tabela


def main(argv=None):
    parser=argparse.ArgumentParser(description="Preflight/DDL da tabela agro staging")
    parser.add_argument("--projeto",required=True)
    parser.add_argument("--dataset",required=True)
    parser.add_argument("--verificar",action="store_true")
    parser.add_argument("--aplicar",action="store_true")
    args=parser.parse_args(argv)
    aprovado=(os.getenv("NIVON_AGRO_STAGING_SCHEMA_APPROVED")=="true"
              and os.getenv("NIVON_AGRO_GCP_WRITE_APPROVED")=="true"
              and os.getenv("NIVON_ZERO_COST_BQ_APPROVED")=="true")
    resposta=verificar_ou_criar_tabela(
        projeto=args.projeto,dataset=args.dataset,
        verificar=args.verificar or args.aplicar,
        aplicar=args.aplicar,aprovado=aprovado)
    print(json.dumps(resposta,ensure_ascii=False,indent=2))
    return 0 if resposta["estado"] not in ("TABELA_AUSENTE",) else 2


if __name__=="__main__":
    raise SystemExit(main())
