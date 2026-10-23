"""Backfill por lotes pequenos de ANTT/SIADE ferroviario no NIVON GCP.

Preserva arquivos oficiais por SHA no GCS e historico de revisoes no BigQuery.
Nunca agenda execucoes, nao habilita o workflow recorrente nem cria projeto,
bucket ou dataset. Falha fechada antes de gravar se QUALQUER ano violar teto.
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

MAX_ANOS = 4
MAX_ARQUIVO = 2_000_000
MAX_BYTES_LOTE = 6_000_000
MAX_LINHAS_ANO = 15_000
MAX_LINHAS_LOTE = 42_000
MAX_BYTES_CONSULTA = 50_000_000
PROJETO = "nivon-data"
DATASET = "nivon_raw"
BUCKET = "nivon-data-raw-2026"


def verificar_anos(anos: list[int]) -> None:
    if (not isinstance(anos, list) or not 1 <= len(anos) <= MAX_ANOS
            or any(type(a) is not int or not 2006 <= a <= 2025 for a in anos)
            or sorted(set(anos)) != sorted(anos)
            or anos != list(range(anos[0], anos[-1]+1))):
        raise ErroTransporte("backfill exige 1 a 4 anos historicos distintos e consecutivos (2006-2025)")


def validar_planos(planos: list[dict], anos: list[int], destino: DestinoBQ, bucket: str) -> None:
    verificar_anos(anos)
    if (destino.projeto != PROJETO or destino.dataset != DATASET
            or destino.tabela != "antt_ferrovia_od_snapshots" or bucket != BUCKET):
        raise ErroTransporte("destino diferente do NIVON autorizado")
    if len(planos) != len(anos):
        raise ErroTransporte("plano historico incompleto")
    soma_bytes, soma_linhas = 0, 0
    for p, ano in zip(planos, anos):
        if (p.get("estado") != "PLANO_VALIDADO_READ_ONLY_SEM_CARGA"
                or p.get("ano") != ano
                or p.get("projeto") != PROJETO
                or p.get("dataset") != DATASET
                or p.get("bucket") != BUCKET
                or p.get("localizacao") != "southamerica-east1"
                or not p.get("bigquery_tabela_existe")
                or p.get("gravacoes_realizadas") != 0
                or type(p.get("bytes_brutos")) is not int
                or not 0 < p["bytes_brutos"] <= MAX_ARQUIVO
                or type(p.get("linhas_ferroviarias")) is not int
                or not 0 < p["linhas_ferroviarias"] <= MAX_LINHAS_ANO
                or not isinstance(p.get("arquivo_sha256"), str)
                or len(p["arquivo_sha256"]) != 64
                or not str(p.get("competencia_maxima_publicada", "")).startswith(str(ano))):
            raise ErroTransporte(f"ano {ano} fora do escopo/limites ou tabela inexistente")
        soma_bytes += p["bytes_brutos"]
        soma_linhas += p["linhas_ferroviarias"]
    if soma_bytes > MAX_BYTES_LOTE or soma_linhas > MAX_LINHAS_LOTE:
        raise ErroTransporte("limite agregado do backfill ultrapassado")


def carregar_historico(*, pasta: str | Path, anos: list[int], destino: DestinoBQ,
                       bucket: str, preparador=preparar_piloto,
                       arquivador=arquivar_gcs, gravador=gravar_bigquery,
                       cliente_bq=None, sdk=None, salvar_progresso=None) -> dict:
    verificar_anos(anos)
    # Leitura de TODOS os arquivos, schemas, hashes e metadados antes do upload.
    planos = [preparador(pasta, ano=ano, destino=destino, bucket=bucket)
              for ano in anos]
    validar_planos(planos, anos, destino, bucket)
    if cliente_bq is None:
        try:
            from google.cloud import bigquery as sdk
        except ImportError:
            raise ErroTransporte("SDK BigQuery nao instalado") from None
        cliente_bq = sdk.Client(project=PROJETO)
    elif sdk is None:
        raise ErroTransporte("SDK testes ausente")
    # Confere bigquery.jobs.create ANTES de modificar GCS.
    conf = sdk.QueryJobConfig(maximum_bytes_billed=0)
    status = list(cliente_bq.query("SELECT 1 AS confirmado", job_config=conf).result(timeout=45))
    if len(status) != 1 or status[0].confirmado != 1:
        raise ErroTransporte("sem permissao confirmada para jobs BigQuery")

    saida = {
        "estado": "BACKFILL_HISTORICO_EM_EXECUCAO",
        "projeto": PROJETO, "dataset": DATASET, "bucket": BUCKET,
        "anos_planejados": anos, "anos_conciliados": [],
        "carga_recorrente_ativada": False, "fonte": "ANTT_SIADE_FERROVIAS",
        "obs": "Volumes ferroviarios declarados, nao transbordos rodoviarios",
    }
    for ano, plano in zip(anos, planos):
        objetos = arquivador(pasta, [ano], bucket, habilitar_escrita=True)
        if (len(objetos) != 1 or objetos[0]["estado"] not in
                ("ARQUIVADO", "JA_ARQUIVADO") or
                objetos[0].get("sha256") != plano["arquivo_sha256"]):
            raise ErroTransporte(f"GCS ano {ano} nao conciliado; parar antes BQ")
        cargas = gravador(pasta, [ano], destino, habilitar_escrita=True,
                         permitir_criar_tabela=False)
        if (len(cargas) != 1 or cargas[0]["estado"] not in
                ("CARREGADO_PENDENTE_CONCILIACAO", "SEM_MUDANCA") or
                cargas[0].get("sha256") != plano["arquivo_sha256"]):
            raise ErroTransporte(f"BigQuery ano {ano} nao conciliado; interromper")
        sql = (f"SELECT COUNT(*) AS n, CAST(SUM(toneladas_uteis) AS STRING) AS tu "
               "FROM " + chr(96) + destino.tabela_completa + chr(96) +
               " WHERE ano=@ano AND arquivo_sha256=@sha")
        job = sdk.QueryJobConfig(
            maximum_bytes_billed=MAX_BYTES_CONSULTA,
            query_parameters=[
                sdk.ScalarQueryParameter("ano", "INT64", ano),
                sdk.ScalarQueryParameter("sha", "STRING", plano["arquivo_sha256"]),
            ])
        rows = list(cliente_bq.query(sql, job_config=job).result(timeout=90))
        if (len(rows) != 1 or int(rows[0].n) != plano["linhas_ferroviarias"] or
                Decimal(rows[0].tu or "-1") !=
                Decimal(plano["toneladas_uteis_declaradas_no_arquivo"])):
            raise ErroTransporte(f"ano {ano} divergencia TU/contagem apos carga")
        item = {
            "ano": ano, "competencia_maxima": plano["competencia_maxima_publicada"],
            "linhas": int(rows[0].n), "toneladas_uteis": str(Decimal(rows[0].tu)),
            "sha256": plano["arquivo_sha256"], "bytes_csv": plano["bytes_brutos"],
            "gcs_estado": objetos[0]["estado"], "bq_estado": cargas[0]["estado"],
            "conferencia": "COUNT_E_SOMA_TU_CONCILIADOS",
        }
        saida["anos_conciliados"].append(item)
        if salvar_progresso is not None:
            salvar_progresso(saida)
        print(json.dumps({"ano_conciliado": item},ensure_ascii=False), flush=True)
    saida["estado"] = "BACKFILL_HISTORICO_CONCILIADO"
    if salvar_progresso is not None:
        salvar_progresso(saida)
    return saida


def main(argv=None):
    parser = argparse.ArgumentParser(description="NIVON: backfill ferroviario com tetos de custo e escopo")
    parser.add_argument("--staging", required=True)
    parser.add_argument("--inicio", type=int, required=True)
    parser.add_argument("--fim", type=int, required=True)
    parser.add_argument("--saida", required=True)
    parser.add_argument("--live", action="store_true")
    parser.add_argument("--confirmar-historico", action="store_true")
    a = parser.parse_args(argv)
    if not a.live or not a.confirmar_historico:
        print("BLOQUEADO_SEM_CONFIRMACOES", file=sys.stderr)
        return 2
    try:
        anos = list(range(a.inicio, a.fim+1))
        destino = DestinoBQ(PROJETO, DATASET)
        out = Path(a.saida)
        out.parent.mkdir(parents=True,exist_ok=True)
        def persistir_parcial(obj):
            out.write_text(json.dumps(obj,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
        r = carregar_historico(pasta=a.staging,anos=anos,destino=destino,bucket=BUCKET,
                              salvar_progresso=persistir_parcial)
        print(json.dumps({"estado":r["estado"],"anos_conciliados":len(r["anos_conciliados"])},
                         ensure_ascii=False))
    except (ErroTransporte, ValueError, OSError) as exc:
        print(json.dumps({"estado":"BACKFILL_INTERROMPIDO_SEM_EXPANSAO",
                          "motivo":str(exc),"tipo":type(exc).__name__},
                         ensure_ascii=False),file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
