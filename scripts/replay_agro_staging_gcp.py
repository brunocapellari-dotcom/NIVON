"""Replay privado IMEA/CONAB GCS -> BigQuery staging por SHA-256.

Sem --executar: 100% offline. Com --executar: requer aprovações explícitas,
WIF/ADC, bucket e tabela já existentes. Nunca consulta a fonte/SQLite.
"""
from __future__ import annotations
import argparse
import json
import os
from nivon.agro_staging_bigquery import (
    reprocessar_stage_quarentena, FONTES,
)


def main(argv=None):
    p=argparse.ArgumentParser(description="NIVON: recuperar estágio agrícola GCS")
    p.add_argument("--fonte-dataset",required=True,choices=sorted(FONTES))
    p.add_argument("--sha256",required=True)
    p.add_argument("--projeto",required=True)
    p.add_argument("--dataset",required=True)
    p.add_argument("--bucket",required=True)
    p.add_argument("--executar",action="store_true")
    a=p.parse_args(argv)
    if a.executar:
        gates=(
            "NIVON_AGRO_GCP_WRITE_APPROVED",
            "NIVON_AGRO_STAGING_BIGQUERY_APPROVED",
            "NIVON_RAW_ARCHIVE_APPROVED",
            "NIVON_ZERO_COST_BQ_APPROVED",
        )
        if not all(os.getenv(gate)=="true" for gate in gates):
            raise PermissionError("replay BigQuery GCP não autorizado")
    resultado=reprocessar_stage_quarentena(
        sha256=a.sha256,fonte_dataset=a.fonte_dataset,bucket=a.bucket,
        project_id=a.projeto,dataset_id=a.dataset,executar=a.executar)
    print(json.dumps(resultado,ensure_ascii=False,indent=2))
    return 0


if __name__=="__main__":
    raise SystemExit(main())
