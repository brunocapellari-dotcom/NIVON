"""Plano read-only da primeira carga ANTT/SIADE no NIVON Google Cloud.

Valida staging ANTT (manifesto, SHA e volumes) e os recursos Google Cloud.
Nunca cria recurso, objeto, consulta SQL, job BigQuery ou credencial.
Executar primeiro para saber se a tabela da carga existe e quais bytes serao
gravados, antes de habilitar qualquer gate de producao.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .antt_bigquery import DestinoBQ, _FIELDS, montar_lote
from .antt_gcs import plano_gcs
from .transporte_multimodal import ErroTransporte


REGIAO_NIVON = "southamerica-east1"
MAX_BYTES_PILOTO = 16_000_000
MAX_REGISTROS_PILOTO = 30_000


def preparar_piloto(
    pasta: str | Path,
    *,
    ano: int,
    destino: DestinoBQ,
    bucket: str,
    cliente_bq=None,
    cliente_gcs=None,
    tipo_not_found=None,
) -> dict:
    """Inspeção de metadados e staging com zero gravacoes.

    Clientes injetados permitem testes sem Google SDK/Internet. No modo real,
    as credenciais sao apenas as temporarias fornecidas pelo GitHub OIDC.
    """
    if type(ano) is not int or not 2006 <= ano <= 2100:
        raise ErroTransporte("ano piloto invalido")
    # Fonte bruta preservada por SHA; o parser ANTT valida contrato e registros.
    rows, meta = montar_lote(pasta, ano)
    planos = plano_gcs(pasta, [ano], bucket)
    if len(planos) != 1 or len(rows) != meta["registros"]:
        raise ErroTransporte("fonte SIADE incoerente")
    payload, objeto = planos[0]
    if not rows or len(rows) > MAX_REGISTROS_PILOTO:
        raise ErroTransporte("total de registros supera limite do piloto")
    if not payload or len(payload) > MAX_BYTES_PILOTO:
        raise ErroTransporte("bytes do arquivo superam limite do piloto")
    if objeto["sha256"] != meta["sha256"]:
        raise ErroTransporte("hash bruto diverge entre GCS e BigQuery")

    if cliente_bq is None or cliente_gcs is None:
        if cliente_bq is not None or cliente_gcs is not None:
            raise ErroTransporte("injetar os dois clientes ou nenhum")
        try:
            from google.cloud import bigquery, storage
            from google.api_core.exceptions import NotFound
        except ImportError:
            raise ErroTransporte("SDK Google Cloud nao instalado") from None
        cliente_bq = bigquery.Client(project=destino.projeto)
        cliente_gcs = storage.Client(project=destino.projeto)
        tipo_not_found = NotFound
    if tipo_not_found is None:
        raise ErroTransporte("excecao NotFound explicita necessaria")

    # get_dataset/get_bucket/get_table/get_blob: apenas leituras de metadados.
    ds = cliente_bq.get_dataset(f"{destino.projeto}.{destino.dataset}")
    b = cliente_gcs.get_bucket(bucket)
    if str(ds.location or "").lower() != REGIAO_NIVON or str(b.location or "").lower() != REGIAO_NIVON:
        raise ErroTransporte("regioes do dataset/bucket divergem de Sao Paulo")
    if getattr(ds, "project", destino.projeto) != destino.projeto or getattr(ds, "dataset_id", destino.dataset) != destino.dataset:
        raise ErroTransporte("dataset diferente do destino selecionado")
    if b.name != bucket:
        raise ErroTransporte("bucket inesperado")

    try:
        tabela = cliente_bq.get_table(destino.tabela_completa)
    except tipo_not_found:
        tabela = None
    if tabela is not None:
        esquema = {f.name: f.field_type for f in tabela.schema}
        if any(esquema.get(k) != typ for k, typ in _FIELDS.items()):
            raise ErroTransporte("tabela ANTT existente tem esquema incompatível")
        if (not tabela.time_partitioning or
            tabela.time_partitioning.field != "data_referencia"):
            raise ErroTransporte("tabela ANTT existente nao particionada corretamente")

    existente = b.get_blob(objeto["objeto"])
    if existente is not None:
        metadata = existente.metadata or {}
        if metadata.get("sha256") != objeto["sha256"]:
            raise ErroTransporte("objeto GCS existente tem SHA conflitante")

    return {
        "estado": "PLANO_VALIDADO_READ_ONLY_SEM_CARGA",
        "projeto": destino.projeto,
        "dataset": destino.dataset,
        "bucket": bucket,
        "localizacao": REGIAO_NIVON,
        "ano": ano,
        "competencia_maxima_publicada": meta["competencia_maxima"],
        "arquivo_sha256": objeto["sha256"],
        "bytes_brutos": len(payload),
        "linhas_ferroviarias": len(rows),
        "toneladas_uteis_declaradas_no_arquivo": meta["toneladas_uteis"],
        "gcs_objeto_ja_arquivado": existente is not None,
        "bigquery_tabela_existe": tabela is not None,
        "bigquery_bootstrap_necessario": tabela is None,
        "limites": {
            "max_bytes_brutos": MAX_BYTES_PILOTO,
            "max_linhas": MAX_REGISTROS_PILOTO,
            "max_anos_por_piloto": 1,
        },
        "fonte": "ANTT_SIADE_ORIGEM_DESTINO",
        "natureza": "TU_DECLARADA_ANTT_NAO_EQUIVALE_A_TRANSBORDO",
        "gravacoes_realizadas": 0,
        "jobs_bigquery_criados": 0,
        "carga_producao_ativada": False,
        "nota": "Plano nao demonstra permissoes de escrita; exige gates e teste de persistencia separado.",
    }


def main(argv=None):
    p = argparse.ArgumentParser(description="NIVON: plano primeiro lote ferroviario GCP sem escrita")
    p.add_argument("--staging", required=True)
    p.add_argument("--ano", type=int, default=2026)
    p.add_argument("--projeto", required=True)
    p.add_argument("--dataset", required=True)
    p.add_argument("--bucket", required=True)
    p.add_argument("--saida", required=True)
    args = p.parse_args(argv)
    try:
        r = preparar_piloto(
            args.staging, ano=args.ano, destino=DestinoBQ(args.projeto, args.dataset),
            bucket=args.bucket)
        arq = Path(args.saida)
        arq.parent.mkdir(parents=True, exist_ok=True)
        arq.write_text(json.dumps(r, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print(json.dumps(r, ensure_ascii=False, sort_keys=True))
    except (ErroTransporte, ValueError, OSError) as exc:
        print(json.dumps({"estado": "PILOTO_NAO_AUTORIZADO_OU_FONTE_INVALIDA",
                          "tipo": type(exc).__name__,
                          "motivo": str(exc)}, ensure_ascii=False), file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
