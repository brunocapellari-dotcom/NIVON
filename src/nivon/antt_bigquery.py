"""Carga opt-in ANTT/SIADE -> BigQuery. Preserva snapshots historicos por SHA.

Nao usa rede nem credenciais ao importar o modulo. O dataset GCP deve existir.
"""
from __future__ import annotations
import argparse
import hashlib
import json
import re
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from pathlib import Path

from .transporte_multimodal import ErroTransporte, interpretar_csv_antt

_FIELDS = {
    "ano": "INTEGER", "competencia": "STRING", "data_referencia": "DATE",
    "data_publicacao": "DATE", "data_coleta": "TIMESTAMP",
    "ferrovia": "STRING", "mercadoria": "STRING",
    "estacao_origem": "STRING", "uf_origem": "STRING",
    "estacao_destino": "STRING", "uf_destino": "STRING",
    "toneladas_uteis": "NUMERIC", "tku_raw": "NUMERIC",
    "unidade_tku_confirmada": "BOOLEAN",
    "natureza_tu": "STRING", "natureza_tku": "STRING",
    "fonte_url": "STRING", "arquivo_sha256": "STRING",
    "linha_id": "STRING", "revisao_fonte": "STRING",
}


@dataclass(frozen=True)
class DestinoBQ:
    projeto: str
    dataset: str
    tabela: str = "antt_ferrovia_od_snapshots"

    def __post_init__(self):
        if not re.fullmatch(r"[a-z][a-z0-9-]{4,28}[a-z0-9]", self.projeto):
            raise ErroTransporte("projeto GCP invalido")
        if any(not re.fullmatch(r"[A-Za-z_][A-Za-z_0-9]{0,1023}", s)
               for s in (self.dataset, self.tabela)):
            raise ErroTransporte("identificador BigQuery invalido")

    @property
    def tabela_completa(self):
        return f"{self.projeto}.{self.dataset}.{self.tabela}"

    @property
    def view_completa(self):
        return f"{self.projeto}.{self.dataset}.vw_antt_ferrovia_od_atual"


def sql_view(d: DestinoBQ) -> str:
    q = chr(96)  # quote identifier, previamente validado
    return f"""CREATE OR REPLACE VIEW {q}{d.view_completa}{q} AS
WITH versoes AS (
 SELECT ano, arquivo_sha256, MAX(data_coleta) AS coleta
 FROM {q}{d.tabela_completa}{q} GROUP BY ano, arquivo_sha256
), ultimas AS (
 SELECT ano, arquivo_sha256 FROM versoes
 QUALIFY ROW_NUMBER() OVER (PARTITION BY ano ORDER BY coleta DESC, arquivo_sha256 DESC)=1
)
SELECT r.* FROM {q}{d.tabela_completa}{q} r
JOIN ultimas u USING (ano, arquivo_sha256)"""


def montar_lote(pasta: str | Path, ano: int) -> tuple[list[dict], dict]:
    p = Path(pasta)
    try:
        manifesto = json.loads((p / "manifesto-antt.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        raise ErroTransporte("manifesto ausente/invalido") from None
    if manifesto.get("formato") != "nivon-antt-staging-v1":
        raise ErroTransporte("contrato do manifesto divergente")
    item = manifesto.get("anos", {}).get(str(ano))
    if not isinstance(item, dict) or item.get("status") != "STAGING_NAO_HOMOLOGADO":
        raise ErroTransporte("ano ausente/invalido no manifesto")
    raw = (p / f"antt-od-{ano}.csv").read_bytes()
    sha = hashlib.sha256(raw).hexdigest()
    if sha != item.get("sha256"):
        raise ErroTransporte("SHA256 bruto divergente")
    try:
        dt = datetime.fromisoformat(item["verificado_utc"].replace("Z", "+00:00"))
    except (ValueError, KeyError, TypeError):
        raise ErroTransporte("data de coleta invalida") from None
    if not dt.tzinfo:
        raise ErroTransporte("data de coleta sem timezone")
    stamp = dt.isoformat()
    linhas, info = interpretar_csv_antt(
        raw, ano=ano, coleta_utc=dt.strftime("%Y-%m-%dT%H:%M:%SZ"),
        fonte_url=item["url"])
    if len(linhas) != item["registros"] or info.referencia_maxima != item["competencia_maxima"]:
        raise ErroTransporte("arquivo bruto nao confere com manifesto")
    if len(linhas) > 200_000:
        raise ErroTransporte("limite de registros excedido")
    rows = []
    for i, x in enumerate(linhas):
        rows.append({
            "ano": ano, "competencia": x["competencia"],
            "data_referencia": x["competencia"] + "-01",
            "data_publicacao": None, "data_coleta": stamp,
            "ferrovia": x["ferrovia"], "mercadoria": x["mercadoria"],
            "estacao_origem": x["estacao_origem"], "uf_origem": x["uf_origem"],
            "estacao_destino": x["estacao_destino"], "uf_destino": x["uf_destino"],
            "toneladas_uteis": x["toneladas_uteis"], "tku_raw": x["tku_raw"],
            "unidade_tku_confirmada": False,
            "natureza_tu": x["natureza_tu"], "natureza_tku": x["natureza_tku"],
            "fonte_url": item["url"], "arquivo_sha256": sha,
            "linha_id": hashlib.sha256(f"{ano}|{sha}|{i}".encode()).hexdigest(),
            "revisao_fonte": str(item.get("revision_id") or ""),
        })
    return rows, {"ano": ano, "registros": len(rows), "sha256": sha,
                  "competencia_maxima": info.referencia_maxima,
                  "toneladas_uteis": str(sum((Decimal(r["toneladas_uteis"]) for r in rows), Decimal(0))),
                  "tku_raw": str(sum((Decimal(r["tku_raw"]) for r in rows), Decimal(0)))}


def gravar_bigquery(pasta: str | Path, anos: list[int], destino: DestinoBQ, *,
                    habilitar_escrita=False, cliente=None, sdk=None) -> list[dict]:
    if not anos or len(set(anos)) != len(anos) or any(type(a) is not int for a in anos):
        raise ErroTransporte("anos invalidos")
    lotes = [montar_lote(pasta, ano) for ano in sorted(anos)]
    if not habilitar_escrita:
        return [{"estado": "DRY_RUN", **meta} for _, meta in lotes]
    if cliente is None:
        try:
            from google.cloud import bigquery as sdk
            from google.api_core.exceptions import NotFound as not_found
        except ImportError:
            raise ErroTransporte("google-cloud-bigquery nao instalado") from None
        cliente = sdk.Client(project=destino.projeto)
    elif sdk is None:
        raise ErroTransporte("SDK de testes ausente")
    else:
        not_found = sdk.NotFound
    # Deliberadamente NAO cria projeto ou dataset, exige escopo autorizado.
    cliente.get_dataset(f"{destino.projeto}.{destino.dataset}")
    ref = destino.tabela_completa
    try:
        t = cliente.get_table(ref)
    except not_found:
        t = sdk.Table(ref, schema=[sdk.SchemaField(k, typ) for k, typ in _FIELDS.items()])
        t.time_partitioning = sdk.TimePartitioning(type_=sdk.TimePartitioningType.MONTH,
                                                   field="data_referencia")
        t.clustering_fields = ["ferrovia", "mercadoria", "uf_origem", "uf_destino"]
        t = cliente.create_table(t)
    campos = {f.name: f.field_type for f in t.schema}
    if any(campos.get(k) != v for k, v in _FIELDS.items()) or \
       not t.time_partitioning or t.time_partitioning.field != "data_referencia":
        raise ErroTransporte("schema/particionamento BQ divergente")
    q = chr(96)
    query = f"SELECT COUNT(*) AS n FROM {q}{ref}{q} WHERE ano=@ano AND arquivo_sha256=@sha"
    result = []
    for rows, meta in lotes:
        conf = sdk.QueryJobConfig(query_parameters=[
            sdk.ScalarQueryParameter("ano", "INT64", meta["ano"]),
            sdk.ScalarQueryParameter("sha", "STRING", meta["sha256"])],
            maximum_bytes_billed=50_000_000)
        qtd = int(list(cliente.query(query, job_config=conf).result())[0].n)
        if qtd == meta["registros"]:
            result.append({"estado": "SEM_MUDANCA", **meta})
            continue
        if qtd:
            raise ErroTransporte("snapshot existente com contagem incorreta")
        config = sdk.LoadJobConfig(schema=[sdk.SchemaField(k, typ) for k, typ in _FIELDS.items()],
                                   source_format=sdk.SourceFormat.NEWLINE_DELIMITED_JSON,
                                   write_disposition=sdk.WriteDisposition.WRITE_APPEND,
                                   max_bad_records=0)
        job = cliente.load_table_from_json(rows, ref, job_config=config,
                        job_id=f"nivon_antt_{meta['ano']}_{meta['sha256'][:24]}")
        job.result(timeout=240)
        if job.errors:
            raise ErroTransporte("job BigQuery falhou")
        conf = sdk.QueryJobConfig(query_parameters=[
            sdk.ScalarQueryParameter("ano", "INT64", meta["ano"]),
            sdk.ScalarQueryParameter("sha", "STRING", meta["sha256"])],
            maximum_bytes_billed=50_000_000)
        depois = int(list(cliente.query(query, job_config=conf).result())[0].n)
        if depois != meta["registros"]:
            raise ErroTransporte("contagem pos-carga nao conciliada")
        result.append({"estado": "CARREGADO_PENDENTE_CONCILIACAO", "job_id": job.job_id, **meta})
    cliente.query(sql_view(destino)).result()
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description="NIVON: snapshots ferroviarios no BigQuery")
    parser.add_argument("--staging", required=True)
    parser.add_argument("--anos", nargs="+", type=int, required=True)
    parser.add_argument("--projeto", required=True)
    parser.add_argument("--dataset", required=True)
    parser.add_argument("--live", action="store_true")
    a = parser.parse_args()
    try:
        resumo = gravar_bigquery(a.staging, a.anos, DestinoBQ(a.projeto, a.dataset),
                                habilitar_escrita=a.live)
    except (ErroTransporte, OSError) as exc:
        print(json.dumps({"estado": "BLOQUEADO", "motivo": str(exc)}, ensure_ascii=False))
        return 2
    print(json.dumps({"destino": "BigQuery", "resultados": resumo}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
