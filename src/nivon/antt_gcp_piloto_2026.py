"""Ativação única, limitada e conciliada do primeiro lote ANTT/SIADE 2026.

Não habilita o workflow recorrente, outros anos, projetos ou datasets.
Exige flags explícitas de CLI e identidade Google Cloud via ADC/WIF.
"""
from __future__ import annotations

import argparse
from decimal import Decimal
import json
from pathlib import Path
import sys

from .antt_bigquery import DestinoBQ, gravar_bigquery
from .antt_gcp_preparar_piloto import preparar_piloto
from .antt_gcs import arquivar_gcs
from .transporte_multimodal import ErroTransporte

ANUALIDADE = 2026
LIMITE_BRUTO_BYTES = 2_000_000
LIMITE_OD = 10_000
LIMITE_CONSULTA_BQ_BYTES = 50_000_000


def conferir_limites_plano(plano: dict, *, destino: DestinoBQ, bucket: str) -> None:
    """Validação fail-closed antes de qualquer escrita ou job de carga."""
    if (plano.get("estado") != "PLANO_VALIDADO_READ_ONLY_SEM_CARGA"
            or plano.get("projeto") != destino.projeto
            or plano.get("dataset") != destino.dataset
            or plano.get("bucket") != bucket
            or plano.get("ano") != ANUALIDADE
            or plano.get("localizacao") != "southamerica-east1"
            or plano.get("gravacoes_realizadas") != 0):
        raise ErroTransporte("plano nao homologado para lote unico")
    if (type(plano.get("bytes_brutos")) is not int
            or not 0 < plano["bytes_brutos"] <= LIMITE_BRUTO_BYTES
            or type(plano.get("linhas_ferroviarias")) is not int
            or not 0 < plano["linhas_ferroviarias"] <= LIMITE_OD):
        raise ErroTransporte("limites de tamanho/linhas para escrita excedidos")
    if (not isinstance(plano.get("arquivo_sha256"), str)
            or len(plano["arquivo_sha256"]) != 64
            or plano.get("competencia_maxima_publicada", "")[:4] != str(ANUALIDADE)):
        raise ErroTransporte("identidade temporal da fonte invalida")


def carregar_uma_vez(*, pasta, destino: DestinoBQ, bucket: str,
                     cliente_bq=None, sdk=None, preparador=preparar_piloto,
                     arquivador=arquivar_gcs, gravador=gravar_bigquery) -> dict:
    """Uma única versão anual da ANTT, com check de jobs antes do upload."""
    plano = preparador(pasta, ano=ANUALIDADE, destino=destino, bucket=bucket)
    conferir_limites_plano(plano, destino=destino, bucket=bucket)
    if cliente_bq is None:
        try:
            from google.cloud import bigquery as sdk
        except ImportError:
            raise ErroTransporte("SDK BigQuery ausente") from None
        cliente_bq = sdk.Client(project=destino.projeto)
    elif sdk is None:
        raise ErroTransporte("SDK teste ausente")

    # Verifica a permissao bigquery.jobs.create ANTES de gravar GCS.
    conf0 = sdk.QueryJobConfig(maximum_bytes_billed=0)
    status = list(cliente_bq.query("SELECT 1 AS confirmado", job_config=conf0).result(timeout=45))
    if len(status) != 1 or status[0].confirmado != 1:
        raise ErroTransporte("BigQuery Job User nao confirmado")

    objetos = arquivador(pasta, [ANUALIDADE], bucket, habilitar_escrita=True)
    if (len(objetos) != 1 or
            objetos[0]["estado"] not in ("ARQUIVADO", "JA_ARQUIVADO") or
            objetos[0]["sha256"] != plano["arquivo_sha256"]):
        raise ErroTransporte("arquivamento GCS nao validado; nenhuma carga BigQuery")

    cargas = gravador(pasta, [ANUALIDADE], destino,
                     habilitar_escrita=True, permitir_criar_tabela=True)
    if (len(cargas) != 1 or
            cargas[0]["estado"] not in ("CARREGADO_PENDENTE_CONCILIACAO", "SEM_MUDANCA") or
            cargas[0]["sha256"] != plano["arquivo_sha256"]):
        raise ErroTransporte("BigQuery reportou carga inconsistente")

    # Validação independente de agregado, SHA e número de linhas.
    # LIMITES explícitos de processamento por consulta; nenhuma query full scan.
    sql = (f"SELECT COUNT(*) AS n, CAST(SUM(toneladas_uteis) AS STRING) AS tu "
           f"FROM " + chr(96) + destino.tabela_completa + chr(96) +
           " WHERE ano=@ano AND arquivo_sha256=@sha")
    jobconf = sdk.QueryJobConfig(query_parameters=[
        sdk.ScalarQueryParameter("ano", "INT64", ANUALIDADE),
        sdk.ScalarQueryParameter("sha", "STRING", plano["arquivo_sha256"]),
    ], maximum_bytes_billed=LIMITE_CONSULTA_BQ_BYTES)
    medicoes = list(cliente_bq.query(sql, job_config=jobconf).result(timeout=90))
    if (len(medicoes) != 1 or int(medicoes[0].n) != plano["linhas_ferroviarias"]
            or Decimal(medicoes[0].tu or "-1") != Decimal(plano["toneladas_uteis_declaradas_no_arquivo"])):
        raise ErroTransporte("falha na reconciliacao contagem/tonelagem; bloquear expansao")

    return {
        "estado": "ANTT_2026_GCS_BIGQUERY_CONCILIADO",
        "projeto": destino.projeto, "dataset": destino.dataset, "bucket": bucket,
        "ano": ANUALIDADE,
        "competencia_maxima": plano["competencia_maxima_publicada"],
        "sha256": plano["arquivo_sha256"],
        "bytes_fonte": plano["bytes_brutos"],
        "linhas_confirmadas": int(medicoes[0].n),
        "toneladas_uteis_confirmadas": str(Decimal(medicoes[0].tu)),
        "gcs_estado": objetos[0]["estado"],
        "bigquery_estado": cargas[0]["estado"],
        "bigquery_tabela": destino.tabela_completa,
        "bigquery_view_atual": destino.view_completa,
        "carga_continua_ativada": False,
        "outros_anos_carregados_pelo_piloto": False,
    }


def main(argv=None):
    p = argparse.ArgumentParser(description="Piloto UNICO ANTT 2026: GCS + BigQuery")
    p.add_argument("--staging", required=True)
    p.add_argument("--projeto", required=True)
    p.add_argument("--dataset", required=True)
    p.add_argument("--bucket", required=True)
    p.add_argument("--saida", required=True)
    p.add_argument("--live", action="store_true")
    p.add_argument("--confirmar-piloto-2026", action="store_true")
    a = p.parse_args(argv)
    if not a.live or not a.confirmar_piloto_2026:
        print(json.dumps({"estado": "BLOQUEADO_SEM_DUAS_CONFIRMACOES"}), file=sys.stderr)
        return 2
    try:
        result = carregar_uma_vez(
            pasta=a.staging,
            destino=DestinoBQ(a.projeto, a.dataset),
            bucket=a.bucket)
        destino = Path(a.saida)
        destino.parent.mkdir(parents=True, exist_ok=True)
        destino.write_text(json.dumps(result,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
        print(json.dumps(result,ensure_ascii=False))
        return 0
    except (ErroTransporte,ValueError,OSError) as exc:
        print(json.dumps({"estado":"PILOTO_2026_FALHOU_SEM_AUTORIZAR_EXPANSAO",
                          "tipo":type(exc).__name__, "erro":str(exc)},
                         ensure_ascii=False), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
