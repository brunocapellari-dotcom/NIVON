"""Replay verificavel de um manifesto GCS para BigQuery, sem refazer coleta."""
from __future__ import annotations

import argparse
import json
import os

from nivon.persistencia_google_cloud import reprocessar_bigquery_do_manifesto


def main(argv=None):
    p=argparse.ArgumentParser(description="NIVON: recuperar MERGE desde GCS")
    p.add_argument("--manifesto-sha", required=True,
                   help="SHA-256 hex de nivon/manifests/<sha>.json")
    p.add_argument("--executar", action="store_true")
    args=p.parse_args(argv)
    destino={
        "bucket":os.getenv("NIVON_GCS_BUCKET",""),
        "project_id":os.getenv("NIVON_BQ_PROJECT",""),
        "dataset_id":os.getenv("NIVON_BQ_DATASET",""),
    }
    if not args.executar:
        print(json.dumps({
            "modo":"PLANO_SEM_REDE", "manifesto_sha256":args.manifesto_sha,
            "passos":["validar direitos","verificar manifesto GCS","verificar SHA JSONL",
                      "confrontar snapshots","MERGE BigQuery idempotente"],
            "executado":False,
        },ensure_ascii=False,indent=2))
        return 0
    if not all(os.getenv(var)=="true" for var in (
            "NIVON_GCP_OPERACIONAL_APROVADO",
            "NIVON_GCP_DIREITOS_DADOS","NIVON_ZERO_COST_BQ_APPROVED")):
        raise PermissionError("reprocessamento bloqueado: IAM/direitos/custos")
    resultado=reprocessar_bigquery_do_manifesto(
        manifesto_sha256=args.manifesto_sha,
        executar=True,
        autorizacoes=frozenset({"COLETA","ARMAZENAMENTO","PROCESSAMENTO"}),
        evidencia=os.getenv("NIVON_GCP_RIGHTS_EVIDENCE",""),
        **destino)
    print(json.dumps(resultado,ensure_ascii=False,indent=2))
    return 0


if __name__=="__main__":
    raise SystemExit(main())
