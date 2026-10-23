"""Vigia read-only de revisoes ANTT/SIADE na view canonica do NIVON.

Compara os CSVs oficiais do ano atual e anterior (SHA, COUNT, soma TU e
ultima competencia) com a revisao ativa no BigQuery. Nunca cria recursos,
faz load, publica view ou substitui dados automaticamente.
"""
from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path

from .antt_bigquery import DestinoBQ, montar_lote
from .transporte_multimodal import ErroTransporte

MAX_BYTES_QUERY = 50_000_000
PROJETO = "nivon-data"
DATASET = "nivon_raw"


def _normalizar_bq(linhas: list[dict]) -> dict[int, dict]:
    saida = {}
    for item in linhas:
        try:
            ano = int(item["ano"])
            sha = str(item["sha256"])
            registros = int(item["registros"])
            t = Decimal(str(item["toneladas_uteis"]))
            competencia = str(item["competencia_maxima"])
            versoes = int(item["versoes"])
        except (ValueError, TypeError, KeyError, InvalidOperation):
            raise ErroTransporte("linha BigQuery invalida") from None
        if (ano in saida or not 2006 <= ano <= 2100 or len(sha) != 64
                or any(x not in "0123456789abcdef" for x in sha)
                or registros <= 0 or not t.is_finite() or t < 0
                or not competencia.startswith(f"{ano}-") or versoes != 1):
            raise ErroTransporte("BigQuery contem mais de uma versao ativa ou valores invalidos")
        saida[ano] = {"sha256": sha, "registros": registros,
                      "toneladas_uteis": t, "competencia_maxima": competencia}
    return saida


def comparar_staging_bq(*, staging: str | Path, anos: list[int], resumos_bq: list[dict]) -> dict:
    if (not isinstance(anos,list) or not 1 <= len(anos) <= 2
            or any(type(y) is not int or not 2025 <= y <= 2100 for y in anos)
            or sorted(set(anos)) != anos):
        raise ErroTransporte("vigia aceita 1 a 2 anos recentes distintos")
    bq = _normalizar_bq(resumos_bq)
    if set(bq) - set(anos):
        raise ErroTransporte("consulta BigQuery retornou anos inesperados")
    saida = []
    for ano in anos:
        _, meta = montar_lote(staging, ano)
        anterior = bq.get(ano)
        atual_tu = Decimal(meta["toneladas_uteis"])
        if anterior is None:
            estado = "ANO_AUSENTE_BQ_NAO_CARREGAR_AUTOMATICAMENTE"
        elif (anterior["sha256"] == meta["sha256"]
              and anterior["registros"] == meta["registros"]
              and anterior["toneladas_uteis"] == atual_tu
              and anterior["competencia_maxima"] == meta["competencia_maxima"]):
            estado = "FONTE_E_BQ_CONCILIADOS"
        elif anterior["sha256"] == meta["sha256"]:
            estado = "MESMO_SHA_TOTAIS_DIVERGENTES_BLOQUEIO"
        else:
            estado = "NOVA_REVISAO_OFICIAL_NAO_CARREGADA"
        saida.append({
            "ano": ano,
            "estado": estado,
            "arquivo_sha256_fonte": meta["sha256"],
            "arquivo_sha256_bq": anterior["sha256"] if anterior else None,
            "linhas_fonte": meta["registros"],
            "linhas_bq": anterior["registros"] if anterior else None,
            "tu_fonte": str(atual_tu),
            "tu_bq": str(anterior["toneladas_uteis"]) if anterior else None,
            "competencia_fonte": meta["competencia_maxima"],
            "competencia_bq": anterior["competencia_maxima"] if anterior else None,
        })
    divergentes = [x["ano"] for x in saida if x["estado"] != "FONTE_E_BQ_CONCILIADOS"]
    return {
        "estado": ("FONTES_SEM_REVISAO_PENDENTE" if not divergentes
                   else "REVISAR_FONTE_ANTES_DE_PUBLICAR"),
        "fonte": "ANTT_SIADE_FERROVIARIO",
        "natureza": "VIGIA_FONTE_OFICIAL_VS_BIGQUERY",
        "periodo_verificado": anos,
        "anos_com_diferenca": divergentes,
        "resultados": saida,
        "escrita_cloud_executada": False,
        "versoes_alteradas": False,
        "recarregamento_automatico_autorizado": False,
    }


def _consulta_bq(*, projeto: str, dataset: str, anos: list[int], cliente=None, sdk=None):
    destino=DestinoBQ(projeto,dataset)
    if projeto != PROJETO or dataset != DATASET:
        raise ErroTransporte("destino BigQuery fora do escopo NIVON")
    if cliente is None:
        try:
            from google.cloud import bigquery as sdk
        except ImportError:
            raise ErroTransporte("google-cloud-bigquery nao instalado") from None
        cliente = sdk.Client(project=projeto)
    elif sdk is None:
        raise ErroTransporte("SDK fake obrigatorio")
    tabela=destino.view_completa
    sql=(
        "SELECT ano, ANY_VALUE(arquivo_sha256) AS sha256, "
        "COUNT(*) AS registros, CAST(SUM(toneladas_uteis) AS STRING) AS toneladas_uteis, "
        "MAX(competencia) AS competencia_maxima, "
        "COUNT(DISTINCT arquivo_sha256) AS versoes "
        "FROM " + chr(96)+tabela+chr(96) +
        " WHERE ano IN UNNEST(@anos) GROUP BY ano ORDER BY ano"
    )
    conf=sdk.QueryJobConfig(
        maximum_bytes_billed=MAX_BYTES_QUERY,
        query_parameters=[sdk.ArrayQueryParameter("anos","INT64",anos)],
    )
    job=cliente.query(sql,job_config=conf)
    return [dict(row.items()) for row in job.result(timeout=120)]


def verificar(*, staging: str | Path, anos: list[int], projeto: str, dataset: str,
              cliente=None, sdk=None) -> dict:
    resumos=_consulta_bq(projeto=projeto,dataset=dataset,anos=anos,
                        cliente=cliente,sdk=sdk)
    return comparar_staging_bq(staging=staging,anos=anos,resumos_bq=resumos)


def main(argv=None) -> int:
    p=argparse.ArgumentParser(description="Vigiar SHA/TU/linhas da ANTT, sem atualizar dados")
    p.add_argument("--staging",required=True)
    p.add_argument("--anos",type=int,nargs="+",required=True)
    p.add_argument("--projeto",required=True)
    p.add_argument("--dataset",required=True)
    p.add_argument("--saida",required=True)
    a=p.parse_args(argv)
    try:
        resultado=verificar(staging=a.staging,anos=a.anos,projeto=a.projeto,dataset=a.dataset)
        resultado["data_verificacao_utc"]=datetime.now(timezone.utc).isoformat()
        output=Path(a.saida)
        output.parent.mkdir(parents=True,exist_ok=True)
        output.write_text(json.dumps(resultado,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    except (ErroTransporte, OSError, ValueError) as exc:
        print(json.dumps({"estado":"VIGIA_ANTT_NAO_VALIDADA","erro":str(exc)},ensure_ascii=False))
        return 2
    print(json.dumps(resultado,ensure_ascii=False))
    return 0 if resultado["estado"] == "FONTES_SEM_REVISAO_PENDENTE" else 3


if __name__=="__main__":
    raise SystemExit(main())
