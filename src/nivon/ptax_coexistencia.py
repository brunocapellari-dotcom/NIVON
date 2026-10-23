"""Adoção segura de RAW PTAX já existente no ledger legado.

Evita duplicar o mesmo payload sob outro schema em
UNIQUE(dataset_id,sha256). Só reusa snapshot legado após conferir bytes,
metadados imutáveis e TODAS as observações normalizadas existentes.
Não altera schema, não apaga snapshots e não concede direitos novos.
"""
from __future__ import annotations

import sqlite3

SCHEMA_LEGADO = "PTAX_ODATA_1"
SCHEMA_RAW = "PTAX_ODATA_RAW_V1"


class ErroCoexistenciaPTAX(ValueError):
    """Colisão de SHA, schema incompatível ou legado corrompido."""


def conferir_observacoes_legadas(
    db: sqlite3.Connection, *, snapshot_id: int,
    payload: bytes, plano: dict, coletado_em: str,
) -> dict:
    """Confere 1:1 todas as linhas do pipeline PTAX já persistidas.

    Reusa deliberadamente o parser legado para conferir consistência de
    suas próprias linhas, NÃO para certificar que float preserva precisão.
    Essa verificação não substitui o parser RAW Decimal independente.
    """
    from .pipeline_api_dados import _normalizar_bytes

    if type(snapshot_id) is not int or snapshot_id < 1:
        raise ErroCoexistenciaPTAX("snapshot_id legado inválido")
    try:
        esperado = dict(_normalizar_bytes(
            payload, "BCB_PTAX", plano, coletado_em,
        ))
        existente = db.execute(
            "SELECT chave,observacao_json FROM nivon_observacoes_api "
            "WHERE snapshot_id=?",
            (snapshot_id,),
        ).fetchall()
    except (sqlite3.Error, ValueError, TypeError, KeyError) as exc:
        raise ErroCoexistenciaPTAX(
            "linhas legadas ausentes, ilegíveis ou incompatíveis"
        ) from exc
    if not existente or len(existente) != len(esperado):
        raise ErroCoexistenciaPTAX("legado incompleto: quantidade de observações diverge")
    atual = dict(existente)
    if atual != esperado:
        raise ErroCoexistenciaPTAX("legado corrompido ou sem equivalência com RAW")
    return {
        "legado_integralmente_conferido": True,
        "quantidade_legado": len(existente),
        "precisao_decimal_legado_homologada": False,
    }


def identificar_schema_snapshot_ptax(
    db: sqlite3.Connection, *, catalogo: dict, sha256: str,
    tamanho: int, tipo: str, evidencia_direitos: str | None,
    payload: bytes, plano: dict, coletado_em: str,
) -> dict:
    """Escolhe RAW para novo SHA ou aceita snapshot legado idêntico.

    Deve ser chamado *dentro* do savepoint que guarda o RAW.
    Conflitos de tipo, fonte, licença, metadados ou schema bloqueiam.
    """
    try:
        row = db.execute(
            "SELECT * FROM nivon_snapshots "
            "WHERE dataset_id='BCB_PTAX' AND sha256=?",
            (sha256,),
        ).fetchone()
    except sqlite3.Error as exc:
        raise ErroCoexistenciaPTAX("ledger snapshots não preparado") from exc
    if row is None:
        return {
            "schema_versao": SCHEMA_RAW, "adotou_snapshot_legado": False,
            "conferencia_legado": None,
        }
    if not isinstance(catalogo, dict) or not isinstance(catalogo.get("datasets"), list):
        raise ErroCoexistenciaPTAX("catálogo ausente")
    fonte = [x["source_id"] for x in catalogo["datasets"]
             if isinstance(x, dict) and x.get("id") == "BCB_PTAX"
             and isinstance(x.get("source_id"), str)]
    if len(fonte) != 1:
        raise ErroCoexistenciaPTAX("fonte de catálogo ambígua")
    if (row["fonte_id"] != fonte[0] or row["bytes"] != tamanho or
            row["mime"] != "application/json" or row["tipo"] != tipo or
            row["evidencia_direitos"] != evidencia_direitos or
            row["competencia"] is not None or row["referencia"] is not None or
            row["publicacao"] is not None):
        raise ErroCoexistenciaPTAX("mesmo SHA com metadados ou direitos divergentes")
    schema = row["schema_versao"]
    if schema == SCHEMA_RAW:
        return {
            "schema_versao": SCHEMA_RAW, "adotou_snapshot_legado": False,
            "conferencia_legado": None,
        }
    if schema != SCHEMA_LEGADO:
        raise ErroCoexistenciaPTAX("schema desconhecido para o SHA PTAX existente")
    conferencia = conferir_observacoes_legadas(
        db, snapshot_id=row["id"], payload=payload,
        plano=plano, coletado_em=coletado_em,
    )
    return {
        "schema_versao": SCHEMA_LEGADO,
        "adotou_snapshot_legado": True,
        "conferencia_legado": conferencia,
    }
