"""Ingestão ÚNICA e isolada da réplica ANTAQ 2025 (fonte TERCEIRA).

Nunca promove a réplica a dado oficial ANTAQ ou movimentação única por rio.
Downloads de dois parquets em revisão fixada, verificações de cardinalidade,
soma por IDCarga única, prova SHA, BigQuery apartado, sem rotina recorrente.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
from decimal import Decimal
import hashlib
import json
from pathlib import Path
import re
import sys

from .antaq_replica_detalhe import resumo_agro, resumo_parquets, soma_carga_unica_2025
from .antaq_replica_hidrovia import ErroReplicaANTAQ

PROJECT = "nivon-data"
DATASET = "nivon_raw"
TABLE = "antaq_replicacao_terceiro_hidrovias_2025"
HF_REPO = "vinicius-souza/antaq"
HF_COMMIT = "ff0349fa6dc8cebcec161ee3ce48f6f73f7f3ba8"
ARQUIVOS = {
    "hidrovia": "silver/Carga_Hidrovia/ano=2025/data.parquet",
    "carga": "silver/Carga/ano=2025/data.parquet",
}
PRODUTOS = {"SOJA", "MILHO", "FARELO_DE_SOJA", "FERTILIZANTES_CAP31"}
MAX_ROWS = 1200
MAX_QUERY_BYTES = 60_000_000
TOTAL_INTERIOR_BASE = Decimal("92431869.759")
VINCULADO_HIDRO_BASE = Decimal("53250176.855")
FIELDS = {
    "snapshot_id": "STRING",
    "ano": "INTEGER",
    "data_referencia": "DATE",
    "data_coleta": "TIMESTAMP",
    "hidrovia": "STRING",
    "navegacao": "STRING",
    "sentido": "STRING",
    "grupo_produto": "STRING",
    "linhas_trechos": "INTEGER",
    "toneladas_trechos": "NUMERIC",
    "hf_revision": "STRING",
    "sha256_hidrovia": "STRING",
    "sha256_carga": "STRING",
    "fonte": "STRING",
    "classificacao": "STRING",
    "aditividade_entre_rios": "BOOLEAN",
    "transbordo_confirmado": "BOOLEAN",
    "dados_oficiais_antaq": "BOOLEAN",
}


def _digest(caminho: str) -> str:
    p = Path(caminho)
    if p.is_symlink() or not p.is_file() or not 100 <= p.stat().st_size <= 65_000_000:
        raise ErroReplicaANTAQ("parquet de entrada ausente, link simbolico ou tamanho excessivo")
    h = hashlib.sha256()
    with p.open("rb") as f:
        for bloco in iter(lambda: f.read(1024 * 1024), b""):
            h.update(bloco)
    return h.hexdigest()


def preparar_lote(hidrovia, carga, *, collected_at: datetime):
    if not isinstance(collected_at, datetime) or collected_at.utcoffset() is None:
        raise ErroReplicaANTAQ("data de coleta precisa de timezone")
    sha_h, sha_c = _digest(str(hidrovia)), _digest(str(carga))
    por_rio = resumo_agro(resumo_parquets(hidrovia, carga))
    unico = soma_carga_unica_2025(hidrovia, carga)
    if (por_rio["estado"] != "REPLICA_2025_TERCEIRO_NAO_HOMOLOGADA"
            or unico["estado"] != "DERIVADO_TERCEIRO_2025_NAO_HOMOLOGADO"
            or unico["ano"] != 2025 or por_rio["ano"] != 2025
            or unico.get("nao_somar_hidrovias") is not True
            or abs(Decimal(str(unico["total_ton"])) - TOTAL_INTERIOR_BASE) > Decimal("1")
            or abs(Decimal(str(unico["ton_com_classificacao_hidrovia"])) - VINCULADO_HIDRO_BASE) > Decimal("1")):
        raise ErroReplicaANTAQ("fonte terceira divergiu da validacao E2E 2025; sem escrita")
    identificador = hashlib.sha256(
        f"{HF_COMMIT}:{sha_h}:{sha_c}:2025".encode("ascii")
    ).hexdigest()
    dt = collected_at.astimezone(timezone.utc).isoformat()
    rows = []
    keys = set()
    for r in por_rio["recortes_agro"]:
        if r["navegacao"] != "Interior" or r["grupo_produto"] not in PRODUTOS:
            continue
        key = (r["hidrovia"], r["navegacao"], r["sentido"], r["grupo_produto"])
        if key in keys:
            raise ErroReplicaANTAQ("duplicata de grupo hidroviario na replica")
        keys.add(key)
        if (not r["hidrovia"] or r["linhas"] <= 0 or
                Decimal(str(r["toneladas"])) < 0):
            raise ErroReplicaANTAQ("recorte hidroviario inesperado")
        row = {
            "snapshot_id": identificador,
            "ano": 2025,
            "data_referencia": "2025-12-31",
            "data_coleta": dt,
            "hidrovia": r["hidrovia"],
            "navegacao": r["navegacao"],
            "sentido": r["sentido"],
            "grupo_produto": r["grupo_produto"],
            "linhas_trechos": int(r["linhas"]),
            "toneladas_trechos": str(r["toneladas"]),
            "hf_revision": HF_COMMIT,
            "sha256_hidrovia": sha_h,
            "sha256_carga": sha_c,
            "fonte": f"https://huggingface.co/datasets/{HF_REPO}",
            "classificacao": "DERIVADO_DE_TERCEIRO_NAO_HOMOLOGADO",
            "aditividade_entre_rios": False,
            "transbordo_confirmado": False,
            "dados_oficiais_antaq": False,
        }
        if set(row) != set(FIELDS):
            raise ErroReplicaANTAQ("schema de dados derivados incompleto")
        rows.append(row)
    if not 1 <= len(rows) <= MAX_ROWS:
        raise ErroReplicaANTAQ("recortes agro interior ausentes ou acima do limite")
    return rows, {
        "estado": "REPLICA_ANTAQ_2025_APENAS_CAMADA_SECUNDARIA",
        "ano": 2025, "snapshot_id": identificador,
        "linhas_hidroviarias": len(rows),
        "hf_revision": HF_COMMIT, "sha256_hidrovia": sha_h,
        "sha256_carga": sha_c,
        "toneladas_trechos_nao_aditivas": str(
            sum((Decimal(x["toneladas_trechos"]) for x in rows), Decimal(0))
        ),
        "toneladas_navegacao_interior_idcarga_unica": str(unico["total_ton"]),
        "toneladas_com_hidrovia_identificada_idcarga_unica": str(
            unico["ton_com_classificacao_hidrovia"]
        ),
        "fonte_direta_antaq": False,
        "classificacao": "DERIVADO_DE_TERCEIRO_NAO_HOMOLOGADO",
    }


def baixar_revisao_fixada():
    from huggingface_hub import hf_hub_download
    # huggingface_hub devolve links simbolicos internos do cache. Resolver
    # somente o objeto do commit fixado; _digest bloqueia symlinks de entrada
    # e exige arquivo regular dentro do limite de 65MB.
    resultado = {}
    for k, v in ARQUIVOS.items():
        path = Path(hf_hub_download(
            repo_id=HF_REPO, repo_type="dataset",
            filename=v, revision=HF_COMMIT))
        resolved = path.resolve(strict=True)
        regular = resolved.is_file() and not resolved.is_symlink()
        dentro_cache = "datasets--vinicius-souza--antaq" in resolved.parts
        tamanho = resolved.stat().st_size if regular else -1
        if not regular or not dentro_cache or not 100 <= tamanho <= 65_000_000:
            # Apenas booleans/tamanhos: nunca divulgar caminho local,
            # credenciais, conteudo dos parquets ou URL assinada.
            raise ErroReplicaANTAQ(
                f"HF_OBJETO_REJEITADO:{k}:regular={regular}:"
                f"cache_esperado={dentro_cache}:bytes={tamanho}")
        resultado[k] = str(resolved)
    return resultado


def persistir(rows, plano, *, cliente=None, sdk=None, not_found=None):
    if (plano["estado"] != "REPLICA_ANTAQ_2025_APENAS_CAMADA_SECUNDARIA"
            or not 1 <= len(rows) <= MAX_ROWS or len(rows) != plano["linhas_hidroviarias"]
            or any(r["snapshot_id"] != plano["snapshot_id"]
                   or r["classificacao"] != "DERIVADO_DE_TERCEIRO_NAO_HOMOLOGADO"
                   or r["dados_oficiais_antaq"] is not False
                   or r["aditividade_entre_rios"] is not False for r in rows)):
        raise ErroReplicaANTAQ("lote externo nao homologado/adulterado; bloqueio de escrita")
    if cliente is None:
        from google.cloud import bigquery as sdk
        from google.api_core.exceptions import NotFound as not_found
        cliente = sdk.Client(project=PROJECT)
    elif sdk is None or not_found is None:
        raise ErroReplicaANTAQ("cliente de teste incompleto")
    d = cliente.get_dataset(f"{PROJECT}.{DATASET}")
    if str(d.location).lower() != "southamerica-east1":
        raise ErroReplicaANTAQ("regiao BigQuery incompatível")
    tabela = f"{PROJECT}.{DATASET}.{TABLE}"
    try:
        tab = cliente.get_table(tabela)
    except not_found:
        tab = sdk.Table(tabela, schema=[sdk.SchemaField(k,v) for k,v in FIELDS.items()])
        tab.time_partitioning=sdk.TimePartitioning(
            type_=sdk.TimePartitioningType.DAY, field="data_referencia")
        tab.clustering_fields=["hidrovia", "grupo_produto", "hf_revision"]
        tab = cliente.create_table(tab)
    if (not tab.time_partitioning or tab.time_partitioning.field != "data_referencia"
            or {f.name:f.field_type for f in tab.schema} != FIELDS):
        raise ErroReplicaANTAQ("tabela de fonte secundaria com schema/particao divergente")
    q = chr(96)
    sql = (f"SELECT COUNT(*) AS n, CAST(SUM(toneladas_trechos) AS STRING) AS tu "
           f"FROM {q}{tabela}{q} "
           "WHERE data_referencia=DATE '2025-12-31' AND snapshot_id=@sha")
    config = sdk.QueryJobConfig(maximum_bytes_billed=MAX_QUERY_BYTES,
        query_parameters=[sdk.ScalarQueryParameter("sha","STRING",plano["snapshot_id"])])
    esperada = Decimal(plano["toneladas_trechos_nao_aditivas"])
    def contar():
        a=list(cliente.query(sql,job_config=config).result(timeout=120))
        if len(a)!=1:raise ErroReplicaANTAQ("consulta BQ nao retornou contagem")
        return (int(a[0].n), Decimal(a[0].tu or "0"))
    antes = contar()
    if antes == (len(rows), esperada):
        estado = "JA_ARQUIVADO_IDEMPOTENTE"
    elif antes != (0, Decimal(0)):
        raise ErroReplicaANTAQ("snapshot secundario parcial ou divergente no BigQuery")
    else:
        job=cliente.load_table_from_json(
            rows, tabela, job_config=sdk.LoadJobConfig(
                schema=[sdk.SchemaField(k,v) for k,v in FIELDS.items()],
                source_format=sdk.SourceFormat.NEWLINE_DELIMITED_JSON,
                write_disposition=sdk.WriteDisposition.WRITE_APPEND,
                max_bad_records=0),
            job_id=f"nivon_antaq_terceiro_2025_{plano['snapshot_id'][:24]}")
        job.result(timeout=240)
        if job.errors:raise ErroReplicaANTAQ("falha reportada pelo BigQuery")
        estado = "GRAVADO_COMO_SECUNDARIO"
    if contar() != (len(rows), esperada):
        raise ErroReplicaANTAQ("reconciliacao BQ de fonte terceira falhou")
    return {**plano, "estado": "ANTAQ_REPLICA_SECUNDARIA_2025_BQ_CONCILIADA",
            "bq_tabela": tabela, "bq_estado": estado,
            "linhas_conciliadas": len(rows),
            "aditividade_rio_confirmada": False,
            "disponivel_na_camada_oficial": False,
            "carga_recorrente_ativada": False}


def main(argv=None):
    a=argparse.ArgumentParser(description="Ponte ANTAQ terceira 2025 -> BQ isolado")
    a.add_argument("--saida",required=True)
    a.add_argument("--live",action="store_true")
    a.add_argument("--aceitar-fonte-terceira",action="store_true")
    opts=a.parse_args(argv)
    if not opts.live or not opts.aceitar_fonte_terceira:
        print(json.dumps({"estado":"BLOQUEADO_SEM_CONFIRMACAO_FONTE_TERCEIRA"}),file=sys.stderr)
        return 2
    try:
        files=baixar_revisao_fixada()
        rows,plano=preparar_lote(files["hidrovia"],files["carga"],
                                collected_at=datetime.now(timezone.utc))
        doc=persistir(rows,plano)
        p=Path(opts.saida)
        p.parent.mkdir(parents=True,exist_ok=True)
        p.write_text(json.dumps(doc,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
        print(json.dumps(doc,ensure_ascii=False))
        return 0
    except (ErroReplicaANTAQ,ValueError,OSError,ImportError,RuntimeError) as exc:
        print(json.dumps({"estado":"REPLICA_ANTAQ_NAO_CARREGADA",
                          "tipo":type(exc).__name__, "motivo":str(exc)[:280]},
                         ensure_ascii=False),file=sys.stderr)
        return 2


if __name__=="__main__":
    raise SystemExit(main())
