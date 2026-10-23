"""Auditoria independente da view atual SIADE no BigQuery apos backfill 2006-2026.

Baseline especifica da prova de 23/10/2026: quantidades e TU por ano foram
observadas nos logs de jobs BigQuery e comparadas ao manifesto SHA de origem.
Nao cria tabelas, objetos, views ou jobs de carga. Apenas consulta limitada.
"""
from __future__ import annotations

import argparse
from decimal import Decimal
import json
from pathlib import Path
import sys

from .antt_bigquery import DestinoBQ
from .transporte_multimodal import ErroTransporte

# Tuplas ano, registros OD, toneladas uteis observados/conciliados nos jobs.
BASELINE = (
    (2006,11499,389112863),(2007,11356,414925023),
    (2008,10791,426520007),(2009,10077,379441316),
    (2010,9467,435248372),(2011,8784,454380212),
    (2012,8493,453199596),(2013,7962,450692632),
    (2014,7278,465880887),(2015,7082,492826108),
    (2016,6962,505184195),(2017,7139,540237780),
    (2018,7598,571621071),(2019,7965,494922270),
    (2020,7748,489619011),(2021,7955,506796406),
    (2022,7972,500767913),(2023,7928,530803169),
    (2024,7911,541945936),(2025,7802,555077765),
    (2026,5081,353466337),
)
MAX_BYTES_CONSULTA = 250_000_000


def auditar_base(rows, *, destino: DestinoBQ, bytes_processados=None) -> dict:
    if (destino.projeto != "nivon-data" or destino.dataset != "nivon_raw"
            or destino.tabela != "antt_ferrovia_od_snapshots"):
        raise ErroTransporte("destino BQ diferente do NIVON canônico")
    rows = list(rows)
    if len(rows) != len(BASELINE):
        raise ErroTransporte("cobertura historica de 21 anos incompleta ou duplicada")
    saida = []
    for observado, esperado in zip(rows, BASELINE):
        ano, qtd, tu = esperado
        if (int(observado.ano) != ano or
                int(observado.registros) != qtd or
                Decimal(str(observado.tu)) != Decimal(tu) or
                int(observado.versoes_sha) != 1):
            raise ErroTransporte(f"ano {ano} diverge da prova oficial anterior; auditar revisao/duplicidade")
        competencia = str(observado.ultima_competencia)
        if (competencia != ("2026-08" if ano == 2026 else f"{ano}-12")):
            raise ErroTransporte(f"competencia incompleta/divergente em {ano}")
        saida.append({
            "ano": ano, "registros": qtd, "toneladas_uteis": str(tu),
            "ultima_competencia": competencia,
            "revisoes_na_visao_atual": 1,
        })
    total_linhas = sum(x["registros"] for x in saida)
    total_tu = sum((int(x["toneladas_uteis"]) for x in saida), 0)
    if (total_linhas != 174850 or total_tu != 9952668869):
        raise ErroTransporte("soma agregada difere do historico verificado")
    return {
        "estado": "AUDITORIA_HISTORICO_BQ_2006_2026_APROVADA",
        "fonte": "ANTT_SIADE_ORIGEM_DESTINO_FERROVIARIO",
        "projeto": destino.projeto, "dataset": destino.dataset,
        "view_consultada": destino.view_completa,
        "anos": len(saida),
        "periodo": "2006-01 a 2026-08",
        "ano_2026_parcial": True,
        "registros_origem_destino_acumulados": total_linhas,
        "toneladas_uteis_ferroviarias_acumuladas": str(total_tu),
        "volumes_rodoviarios_ou_transbordos_comprovados": False,
        "bytes_processados_job": bytes_processados,
        "limite_bytes_cobraveis_por_consulta": MAX_BYTES_CONSULTA,
        "por_ano": saida,
    }


def consultar(*, destino: DestinoBQ, cliente=None, sdk=None) -> dict:
    if (destino.projeto != "nivon-data" or destino.dataset != "nivon_raw"):
        raise ErroTransporte("GCP destino não autorizado")
    if cliente is None:
        try:
            from google.cloud import bigquery as sdk
        except ImportError:
            raise ErroTransporte("google-cloud-bigquery nao instalado") from None
        cliente = sdk.Client(project=destino.projeto)
    elif sdk is None:
        raise ErroTransporte("SDK fake ausente")
    sql = (
        "SELECT ano, COUNT(*) AS registros, "
        "CAST(SUM(toneladas_uteis) AS STRING) AS tu, "
        "MAX(competencia) AS ultima_competencia, "
        "COUNT(DISTINCT arquivo_sha256) AS versoes_sha "
        "FROM " + chr(96) + destino.view_completa + chr(96) +
        " WHERE ano BETWEEN 2006 AND 2026 GROUP BY ano ORDER BY ano"
    )
    job = cliente.query(sql, job_config=sdk.QueryJobConfig(
        maximum_bytes_billed=MAX_BYTES_CONSULTA))
    rows = list(job.result(timeout=120))
    return auditar_base(rows, destino=destino,
                        bytes_processados=getattr(job, "total_bytes_processed", None))


def main(argv=None):
    ap = argparse.ArgumentParser(description="Auditoria BQ read-only dos 21 anos ferroviarios ANTT")
    ap.add_argument("--projeto", required=True)
    ap.add_argument("--dataset", required=True)
    ap.add_argument("--saida", required=True)
    args = ap.parse_args(argv)
    try:
        result = consultar(destino=DestinoBQ(args.projeto,args.dataset))
        out = Path(args.saida)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(result,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
        print(json.dumps({
            "estado":result["estado"],"anos":result["anos"],
            "registros":result["registros_origem_destino_acumulados"],
            "tu":result["toneladas_uteis_ferroviarias_acumuladas"],
            "bytes_processados_job":result["bytes_processados_job"],
        },ensure_ascii=False))
        return 0
    except (ErroTransporte,ValueError,OSError) as exc:
        print(json.dumps({"estado":"AUDITORIA_HISTORICA_BLOQUEADA",
                          "motivo":str(exc)},ensure_ascii=False),file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
