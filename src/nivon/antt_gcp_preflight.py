"""Preflight somente de metadados da tabela ferroviaria no BigQuery.

Nao faz SELECT, job, scan de linhas, criacao de tabela, upload ou IAM.
Distingue tabela ausente, schema incorreto e view incorreta; nao deduz
permissao de escrita de uma leitura bem-sucedida.
"""
from __future__ import annotations

import argparse
import json
from dataclasses import dataclass

from .antt_bigquery import DestinoBQ, _FIELDS
from .transporte_multimodal import ErroTransporte


def _tipo_normalizado(tipo: str) -> str:
    canonicos = {"INT64":"INTEGER", "DECIMAL":"NUMERIC", "BOOL":"BOOLEAN"}
    return canonicos.get(str(tipo).upper(), str(tipo).upper())


def _not_found(exc: BaseException) -> bool:
    try:
        from google.api_core.exceptions import NotFound
    except ImportError:
        return exc.__class__.__name__ == "NotFound"
    return isinstance(exc, NotFound) or exc.__class__.__name__ == "NotFound"


def _metadata(cliente, ref):
    try:
        return cliente.get_table(ref)
    except Exception as exc:
        if _not_found(exc):
            return None
        raise


def verificar_tabela_antt(*, projeto: str, dataset: str, cliente=None) -> dict:
    """Nunca gera jobs BigQuery; retorna um contrato seguro de observabilidade."""
    destino = DestinoBQ(projeto, dataset)
    if cliente is None:
        try:
            from google.cloud import bigquery
        except ImportError:
            raise ErroTransporte("google-cloud-bigquery nao instalado") from None
        cliente = bigquery.Client(project=projeto)
    # O recurso de destino ja existe segundo prova WIF; verificar novamente.
    ds = cliente.get_dataset(f"{projeto}.{dataset}")
    t = _metadata(cliente, destino.tabela_completa)
    base = {
        "projeto": projeto,
        "dataset": dataset,
        "tabela": destino.tabela_completa,
        "view": destino.view_completa,
        "consulta_sql_executada": False,
        "job_bigquery_criado": False,
        "alteracao_de_recursos": False,
        "permissao_escrita_comprovada": False,
        "carga_antt_comprovada": False,
    }
    if t is None:
        return {
            **base,
            "estado": "TABELA_ANTT_AUSENTE",
            "bootstrap_necessario": True,
            "view_atual_verificada": False,
            "tabela_pronta_para_carga": False,
        }
    tipos = {f.name: _tipo_normalizado(f.field_type) for f in t.schema}
    esperados = {k: _tipo_normalizado(v) for k, v in _FIELDS.items()}
    divergentes = sorted(k for k, esperado in esperados.items()
                         if tipos.get(k) != esperado)
    part = getattr(t, "time_partitioning", None)
    part_ok = (part is not None and getattr(part, "field", None) == "data_referencia"
               and str(getattr(part, "type_", "")).upper().endswith("MONTH"))
    clustering = list(getattr(t, "clustering_fields", None) or [])
    esperado_cluster = ["ferrovia", "mercadoria", "uf_origem", "uf_destino"]
    cluster_ok = clustering == esperado_cluster
    view = _metadata(cliente, destino.view_completa)
    view_ok = (view is not None and getattr(view, "table_type", "") == "VIEW"
               and destino.tabela_completa in str(getattr(view, "view_query", "")))
    valido = not divergentes and part_ok and cluster_ok
    if not valido:
        estado = "ESQUEMA_ANTT_DIVERGENTE"
    elif not view_ok:
        estado = "TABELA_ANTT_OK_VIEW_AUSENTE_OU_DIVERGENTE"
    else:
        estado = "METADADOS_ANTT_OK_SEM_PROVA_DE_CARGA"
    return {
        **base,
        "estado": estado,
        "bootstrap_necessario": False,
        "tabela_pronta_para_carga": valido,
        "view_atual_verificada": view_ok,
        "campos_divergentes": divergentes,
        "particao_mensal_confirmada": part_ok,
        "cluster_confirmado": cluster_ok,
        "numero_linhas_estimado_metadados": getattr(t, "num_rows", None),
    }


def main() -> int:
    p = argparse.ArgumentParser(description="NIVON: ANTT BigQuery pronto? Somente metadados")
    p.add_argument("--projeto", required=True)
    p.add_argument("--dataset", required=True)
    a = p.parse_args()
    try:
        resultado = verificar_tabela_antt(projeto=a.projeto, dataset=a.dataset)
    except (ErroTransporte, OSError) as exc:
        print(json.dumps({"estado":"PREFLIGHT_FALHOU","erro":str(exc)},ensure_ascii=False))
        return 2
    print(json.dumps(resultado,ensure_ascii=False,default=str))
    # Tabela ausente e um resultado diagnostico valido, nao um erro da conexao WIF.
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
