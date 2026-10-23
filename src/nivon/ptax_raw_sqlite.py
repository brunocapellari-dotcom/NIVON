"""Persistência PTAX local: bytes HTTP originais + versões de coleta.

Usa o ledger de snapshots já existente, sem duplicar a orquestração de
fontes. Não converte valores a float e não inventa publication-time.
SQLITE local não é WORM; reconciliação com fonte externa é outra etapa.
"""
from __future__ import annotations

from hashlib import sha256
import json
import sqlite3
from typing import Mapping

from .captura_ptax_http import _autorizado
from .ptax_odata_bruta_mercados import verificar_ptax_odata_bruta
from .qualidade_mercados import _momento
from .registro_snapshots import registrar_snapshot
from .transacoes_sqlite import savepoint_atomico
from .ptax_coexistencia import identificar_schema_snapshot_ptax


class ErroRawPTAX(ValueError):
    """Falha de origem, conteúdo, transação ou leitura temporal."""


def preparar_tabelas_raw_ptax(db: sqlite3.Connection) -> None:
    """Não usa executescript, para preservar savepoints/transações externas."""
    db.execute("""CREATE TABLE IF NOT EXISTS nivon_ptax_raw_blobs (
        sha256 TEXT PRIMARY KEY,
        dados BLOB NOT NULL,
        bytes INTEGER NOT NULL CHECK(bytes > 0)
    )""")
    db.execute("""CREATE TABLE IF NOT EXISTS nivon_ptax_raw_capturas (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        snapshot_id INTEGER NOT NULL REFERENCES nivon_snapshots(id),
        sha256 TEXT NOT NULL REFERENCES nivon_ptax_raw_blobs(sha256),
        coletado_em TEXT NOT NULL,
        consulta_url TEXT NOT NULL,
        moeda TEXT NOT NULL CHECK(moeda IN ('USD','EUR')),
        tipo TEXT NOT NULL CHECK(tipo IN ('SINTETICO','REAL_AUTORIZADO')),
        origem_execucao TEXT NOT NULL,
        headers_json TEXT NOT NULL,
        UNIQUE(sha256, coletado_em, consulta_url, tipo)
    )""")
    db.execute("""CREATE INDEX IF NOT EXISTS idx_nivon_ptax_raw_tempo
                 ON nivon_ptax_raw_capturas(coletado_em, id)""")


def guardar_raw_ptax(
    db: sqlite3.Connection, catalogo: dict, captura: Mapping, *,
    autorizacoes: frozenset[str] = frozenset(),
    evidencia_direitos: str | None = None,
) -> dict:
    """Valida e grava raw em uma transação, respeitando o gate do catálogo.

    Não cria uma coleta real a partir de uma fixture injetada. Uma dict
    fornecida por chamador não prova transporte TLS real; a fronteira de
    confiança é o coletor autorizado que chama a API.
    """
    if not isinstance(db, sqlite3.Connection):
        raise ErroRawPTAX("conexão sqlite inválida")
    if not isinstance(captura, Mapping):
        raise ErroRawPTAX("captura ausente")
    tipo = captura.get("tipo")
    origem = captura.get("origem_execucao")
    if tipo not in ("SINTETICO", "REAL_AUTORIZADO"):
        raise ErroRawPTAX("tipo de captura inválido")
    if ((tipo == "SINTETICO" and origem != "TRANSPORTE_INJETADO_SINTETICO")
            or (tipo == "REAL_AUTORIZADO" and origem != "HTTP_HTTPS_BCB_REAL_NAO_HOMOLOGADO")):
        raise ErroRawPTAX("origem/tipo incoerentes")
    if tipo == "REAL_AUTORIZADO":
        _autorizado(catalogo, autorizacoes, evidencia_direitos)
    elif autorizacoes or evidencia_direitos is not None:
        raise ErroRawPTAX("fixture não pode simular direitos reais")
    plano = captura.get("plano")
    if not isinstance(plano, dict) or plano.get("dataset_id") != "BCB_PTAX":
        raise ErroRawPTAX("plano ausente")
    raw = captura.get("raw_bytes")
    digest = captura.get("raw_sha256")
    if not isinstance(raw, bytes) or sha256(raw).hexdigest() != digest:
        raise ErroRawPTAX("bytes brutos divergentes do SHA")
    coleta_txt = captura.get("coletado_em")
    try:
        coleta = _momento(coleta_txt, "coletado_em").isoformat()
        prova = verificar_ptax_odata_bruta(
            raw, consulta_url=plano["url"], moeda=plano["moeda"],
            coletado_em=coleta, as_of=coleta, raw_sha256_esperado=digest,
        )
    except (KeyError, TypeError, ValueError) as exc:
        raise ErroRawPTAX("contrato da captura PTAX inválido") from exc
    headers = captura.get("cabecalhos_http")
    if not isinstance(headers, Mapping) or set(headers) != {
        "content-type", "date", "etag", "last-modified", "content-length"
    } or any(v is not None and (not isinstance(v, str) or len(v) > 512 or
              "\n" in v or "\r" in v) for v in headers.values()):
        raise ErroRawPTAX("cabeçalhos de captura inválidos")
    meta = json.dumps(dict(headers), ensure_ascii=True, sort_keys=True,
                      separators=(",", ":"))
    preparar_tabelas_raw_ptax(db)
    with savepoint_atomico(db):
        coexistencia = identificar_schema_snapshot_ptax(
            db, catalogo=catalogo, sha256=digest, tamanho=len(raw),
            tipo=tipo, evidencia_direitos=evidencia_direitos,
            payload=raw, plano=plano, coletado_em=coleta,
        )
        snapshot = registrar_snapshot(
            db, catalogo, dataset_id="BCB_PTAX", sha256=digest,
            tamanho=len(raw), mime="application/json",
            schema_versao=coexistencia["schema_versao"], coletado_em=coleta,
            tipo=tipo, autorizacoes=autorizacoes,
            evidencia_direitos=evidencia_direitos,
        )
        anterior = db.execute(
            "SELECT dados,bytes FROM nivon_ptax_raw_blobs WHERE sha256=?",
            (digest,),
        ).fetchone()
        if anterior is not None:
            if anterior[0] != raw or anterior[1] != len(raw):
                raise ErroRawPTAX("mesmo SHA com bytes incompatíveis")
        else:
            db.execute(
                "INSERT INTO nivon_ptax_raw_blobs (sha256,dados,bytes) VALUES (?,?,?)",
                (digest, raw, len(raw)),
            )
        linha = db.execute(
            "SELECT id FROM nivon_snapshots WHERE dataset_id='BCB_PTAX' AND sha256=?",
            (digest,),
        ).fetchone()
        if linha is None:
            raise ErroRawPTAX("snapshot referenciado ausente")
        antes = db.execute(
            "SELECT headers_json,origem_execucao,snapshot_id FROM "
            "nivon_ptax_raw_capturas WHERE sha256=? AND coletado_em=? "
            "AND consulta_url=? AND tipo=?",
            (digest, coleta, plano["url"], tipo),
        ).fetchone()
        if antes is not None and tuple(antes) != (meta, origem, linha[0]):
            raise ErroRawPTAX("mesma captura repetida com metadados divergentes")
        if antes is None:
            db.execute(
                "INSERT INTO nivon_ptax_raw_capturas "
                "(snapshot_id,sha256,coletado_em,consulta_url,moeda,tipo,"
                "origem_execucao,headers_json) VALUES (?,?,?,?,?,?,?,?)",
                (linha[0], digest, coleta, plano["url"], plano["moeda"],
                 tipo, origem, meta),
            )
    return {
        "status": "RAW_PTAX_ARMAZENADO_LOCAL_SEM_PUBLICACAO",
        "tipo": tipo, "sha256": digest, "coleta": coleta,
        "boletins": prova["boletins_distintos"],
        "nova_captura": antes is None,
        "nova_versao_snapshot": snapshot["nova_versao"],
        "adotou_snapshot_legado": coexistencia["adotou_snapshot_legado"],
        "schema_snapshot_preservado": coexistencia["schema_versao"],
        "raw_preservado": True, "publicavel": False,
    }


def consultar_raw_ptax_asof(
    db: sqlite3.Connection, *, corte: str, moeda: str = "USD",
    incluir_sinteticos: bool = False,
) -> dict:
    """Retorna uma única captura mais recente; também revalida o raw e SHA.

    Útil para inspeção; não é prova do momento de publicação BCB.
    """
    if moeda not in ("USD", "EUR") or type(incluir_sinteticos) is not bool:
        raise ErroRawPTAX("moeda ou flag inválida")
    instante = _momento(corte, "corte").isoformat()
    preparar_tabelas_raw_ptax(db)
    linha = db.execute(
        "SELECT c.sha256, c.coletado_em, c.consulta_url, c.tipo, "
        "c.headers_json, b.dados, s.schema_versao, s.id "
        "FROM nivon_ptax_raw_capturas c "
        "JOIN nivon_ptax_raw_blobs b ON b.sha256=c.sha256 "
        "JOIN nivon_snapshots s ON s.id=c.snapshot_id "
        "JOIN nivon_coletas v ON v.snapshot_id=s.id "
        "AND v.coletado_utc=c.coletado_em "
        "WHERE c.coletado_em<=? AND c.moeda=? "
        "AND s.dataset_id='BCB_PTAX' AND s.sha256=c.sha256 "
        "AND s.tipo=c.tipo "
        "AND s.schema_versao IN ('PTAX_ODATA_RAW_V1','PTAX_ODATA_1') "
        "AND ((c.tipo='SINTETICO' AND "
        "c.origem_execucao='TRANSPORTE_INJETADO_SINTETICO') "
        "OR (c.tipo='REAL_AUTORIZADO' "
        "AND c.origem_execucao='HTTP_HTTPS_BCB_REAL_NAO_HOMOLOGADO' "
        "AND s.evidencia_direitos IS NOT NULL)) "
        "AND (?=1 OR c.tipo='REAL_AUTORIZADO') "
        "ORDER BY c.coletado_em DESC,c.id DESC LIMIT 1",
        (instante, moeda, int(incluir_sinteticos)),
    ).fetchone()
    if linha is None:
        return {"status": "SEM_RAW_PTAX_ATE_CORTE", "publicavel": False}
    digest, coleta, url, tipo, headers, raw, schema, snapshot_id = linha
    if type(raw) is not bytes or sha256(raw).hexdigest() != digest:
        raise ErroRawPTAX("arquivo bruto persistido foi adulterado")
    from .ptax_odata_bruta_mercados import _consulta
    from .ptax_plano import planejar_consultas_ptax
    try:
        start, end = _consulta(url, moeda)
        if schema == "PTAX_ODATA_1":
            from .ptax_coexistencia import conferir_observacoes_legadas
            plano = planejar_consultas_ptax(
                moeda=moeda, inicio=start.isoformat(), fim=end.isoformat(),
                dias_janela=(end-start).days+1,
            )[0]
            conferir_observacoes_legadas(
                db, snapshot_id=snapshot_id, payload=raw,
                plano=plano, coletado_em=coleta,
            )
        validado = verificar_ptax_odata_bruta(
            raw, consulta_url=url, moeda=moeda, coletado_em=coleta,
            as_of=instante, raw_sha256_esperado=digest,
        )
        cabecalhos = json.loads(headers)
        if not isinstance(cabecalhos, dict) or set(cabecalhos) != {
            "content-type", "date", "etag", "last-modified", "content-length"
        }:
            raise ErroRawPTAX("cabeçalhos persistidos inválidos")
    except (TypeError, ValueError, sqlite3.Error, IndexError) as exc:
        raise ErroRawPTAX("integridade do snapshot RAW PTAX comprometida") from exc
    return {
        "status": "RAW_PTAX_ASOF_RECONFERIDO_LOCAL",
        "sha256": digest, "coleta": coleta,
        "tipo": tipo, "boletins": validado["boletins"],
        "headers": cabecalhos,
        "schema_snapshot_preservado": schema,
        "apto_backtest_por_publicacao": False,
        "publicavel": False,
    }
