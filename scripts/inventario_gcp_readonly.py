"""Inventário real de metadados GCP NIVON, sem SQL, leitura de dados ou escrita.

Não cria datasets, tabelas, buckets, jobs ou identidades. Ausências e falta
de permissão permanecem distintas no relatório.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import re

PROJECT = re.compile(r"^[a-z][a-z0-9-]{4,61}[a-z0-9]$")
DATASET = re.compile(r"^[A-Za-z_][A-Za-z0-9_]{0,255}$")
BUCKET = re.compile(r"^[a-z0-9][a-z0-9.\-_]{1,220}[a-z0-9]$")
REGIAO = "southamerica-east1"
ALVOS = (
    ("nivon_raw", "nivon_observacoes", "data_referencia",
     {"data_referencia": "DATE", "data_coleta": "TIMESTAMP", "data_publicacao": "TIMESTAMP"}),
    ("nivon_stage", "neon_legado", "data_particao",
     {"data_particao": "DATE", "data_coleta": "TIMESTAMP", "data_referencia": "DATE"}),
    ("nivon_stage", "zarc_linhas_mt", "data_particao",
     {"data_particao": "DATE", "data_coleta": "TIMESTAMP"}),
    ("nivon_core", "ptax_quotes", "reference_date",
     {"reference_date": "DATE", "first_collected_at": "TIMESTAMP"}),
)


class ErroInventario(ValueError):
    pass


def _validar(projeto, bucket, dataset_raw):
    if not isinstance(projeto, str) or not PROJECT.fullmatch(projeto):
        raise ErroInventario("projeto GCP invalido")
    if not isinstance(bucket, str) or not BUCKET.fullmatch(bucket):
        raise ErroInventario("bucket GCS invalido")
    if not isinstance(dataset_raw, str) or not DATASET.fullmatch(dataset_raw):
        raise ErroInventario("dataset RAW invalido")


def inventariar(*, projeto, dataset_raw, bucket, bq, gcs, not_found, forbidden):
    """Retorna estados baseados EXCLUSIVAMENTE nos metadados consultados."""
    _validar(projeto, bucket, dataset_raw)
    ds = bq.get_dataset(f"{projeto}.{dataset_raw}")
    storage_bucket = gcs.get_bucket(bucket)
    if (ds.project != projeto or ds.dataset_id != dataset_raw or
            storage_bucket.name != bucket or
            str(ds.location).lower() != REGIAO or
            str(storage_bucket.location).lower() != REGIAO):
        raise ErroInventario("GCP RAW/bucket diferentes do ambiente confirmado")
    estado_ds = {dataset_raw: "EXISTE"}
    for nome in sorted({a[0] for a in ALVOS} - {dataset_raw}):
        try:
            d = bq.get_dataset(f"{projeto}.{nome}")
        except not_found:
            estado_ds[nome] = "AUSENTE"
        except forbidden:
            estado_ds[nome] = "SEM_ACESSO"
        else:
            estado_ds[nome] = ("EXISTE" if d.project == projeto and d.dataset_id == nome
                              and str(d.location).lower() == REGIAO else "REGIAO_DIVERGENTE")
    tabelas = []
    for ds_nome, tabela, particao, esquema in ALVOS:
        estado = estado_ds[ds_nome]
        nome_completo = f"{projeto}.{ds_nome}.{tabela}"
        if estado != "EXISTE":
            tabelas.append({"tabela": nome_completo, "estado": "DATASET_" + estado})
            continue
        try:
            t = bq.get_table(nome_completo)
        except not_found:
            tabelas.append({"tabela": nome_completo, "estado": "AUSENTE"})
            continue
        except forbidden:
            tabelas.append({"tabela": nome_completo, "estado": "SEM_ACESSO"})
            continue
        campos = {f.name: str(f.field_type).upper() for f in t.schema}
        valido = (all(campos.get(k) == tipo for k, tipo in esquema.items()) and
                  t.time_partitioning is not None and
                  t.time_partitioning.field == particao and
                  bool(t.require_partition_filter))
        tabelas.append({"tabela": nome_completo,
                        "estado": "ESQUEMA_VALIDADO" if valido else "ESQUEMA_DIVERGENTE",
                        "particao": t.time_partitioning.field if t.time_partitioning else None})
    pronto = all(x["estado"] == "ESQUEMA_VALIDADO" for x in tabelas)
    return {"estado": "DESTINOS_EXISTENTES_VALIDOS" if pronto else "DESTINOS_PENDENTES",
            "projeto": projeto, "dataset_raw": dataset_raw, "bucket": bucket,
            "regiao_verificada": REGIAO, "datasets": estado_ds, "tabelas": tabelas,
            "alteracoes": 0, "consultas_sql": 0, "dados_lidos": 0,
            "gravacao_validada": False, "carga_realizada": False}


def main(argv=None):
    p = argparse.ArgumentParser(description="Inventariar tabelas NIVON read-only sem jobs BigQuery")
    p.add_argument("--projeto", required=True)
    p.add_argument("--dataset-raw", required=True)
    p.add_argument("--bucket", required=True)
    args = p.parse_args(argv)
    from google.cloud import bigquery, storage
    from google.api_core.exceptions import NotFound, Forbidden
    r = inventariar(projeto=args.projeto, dataset_raw=args.dataset_raw,
                   bucket=args.bucket,
                   bq=bigquery.Client(project=args.projeto),
                   gcs=storage.Client(project=args.projeto),
                   not_found=NotFound, forbidden=Forbidden)
    print(json.dumps(r, ensure_ascii=False, sort_keys=True))
    # A ausência de uma tabela é um diagnóstico, não gatilho para criá-la.
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
