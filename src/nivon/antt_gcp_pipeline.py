"""Fluxo integrado ANTT/SIADE -> staging -> GCS bruto -> BigQuery analitico.

Uso opt-in, credenciais exclusivamente por ADC/WIF externo. Nenhum projeto,
bucket ou dataset e criado pelo fluxo; falha se recurso autorizado nao existir.
"""
from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path

from .antt_bigquery import DestinoBQ, gravar_bigquery
from .antt_gcs import arquivar_gcs
from .coleta_antt import coletar
from .transporte_multimodal import ErroTransporte


def executar_pipeline(*, pasta: str | Path, anos: list[int], projeto: str,
                     dataset: str, bucket: str, habilitar_live=False,
                     coletor=coletar, arquivador=arquivar_gcs,
                     publicador=gravar_bigquery) -> dict:
    """Em dry-run nao faz rede nem escrita; em live valida fonte e arquiva antes da carga."""
    destino = DestinoBQ(projeto, dataset)
    if not anos or len(anos) != len(set(anos)) or any(type(y) is not int or not 2006 <= y <= 2100 for y in anos):
        raise ErroTransporte("anos invalidos")
    if not habilitar_live:
        return {
            "estado": "PLANO_SEM_EXECUCAO",
            "anos": sorted(anos), "projeto": destino.projeto,
            "dataset": destino.dataset, "bucket": bucket,
            "etapas": ["coleta_http_antt", "arquivamento_gcs", "carga_bigquery", "consulta_view"],
        }
    pasta = Path(pasta)
    coleta = coletor(destino=pasta, anos=sorted(anos), habilitar_rede=True)
    objetos = arquivador(pasta, sorted(anos), bucket, habilitar_escrita=True)
    if len(objetos) != len(anos) or any(r["estado"] not in ("ARQUIVADO", "JA_ARQUIVADO") for r in objetos):
        raise ErroTransporte("arquivamento bruto incompleto; banco nao sera alterado")
    cargas = publicador(pasta, sorted(anos), destino, habilitar_escrita=True)
    if len(cargas) != len(anos) or any(
            r["estado"] not in ("CARREGADO_PENDENTE_CONCILIACAO", "SEM_MUDANCA") for r in cargas):
        raise ErroTransporte("carga analitica incompleta")
    return {"estado": "GCP_CARREGADO_NAO_HOMOLOGADO",
            "anos": sorted(anos), "coleta": coleta, "gcs": objetos, "bigquery": cargas}


def main() -> int:
    ap = argparse.ArgumentParser(description="NIVON — coleta ferroviaria ANTT para GCP")
    ap.add_argument("--staging", required=True)
    ap.add_argument("--projeto", required=True)
    ap.add_argument("--dataset", required=True)
    ap.add_argument("--bucket", required=True)
    ap.add_argument("--inicio", type=int, required=True)
    ap.add_argument("--fim", type=int, required=True)
    ap.add_argument("--live", action="store_true")
    a = ap.parse_args()
    if a.inicio > a.fim or a.fim-a.inicio > 25:
        ap.error("intervalo de anos invalido")
    try:
        result = executar_pipeline(
            pasta=a.staging, anos=list(range(a.inicio, a.fim+1)),
            projeto=a.projeto, dataset=a.dataset, bucket=a.bucket,
            habilitar_live=a.live)
    except (ErroTransporte, OSError) as exc:
        print(json.dumps({"estado": "FALHA_FECHADA", "erro": str(exc)}, ensure_ascii=False))
        return 2
    # Pode conter URL de fonte, SHA e contagens; nunca inclui access token.
    print(json.dumps(result, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
