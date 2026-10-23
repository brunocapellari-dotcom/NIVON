"""Quarentena de respostas PTAX reais recebidas externamente, sem promover à produção.

Aceita bytes *observados fora deste processo* acompanhados de manifest
de captura. O manifest é DECLARADO pelo importador: não prova que houve
TLS, horário confiável, fonte BCB nem direitos de redistribuição.

Separação rigorosa: não escreve no ledger operacional nivon_snapshots,
não alimenta briefing ou previsões, nunca classifica REAL_AUTORIZADO.
Permite registrar OData vazio (feriado/dia sem retorno) sem inventar cotação.
"""
from __future__ import annotations

from datetime import timezone
from decimal import Decimal
from hashlib import sha256
import json
import re
import sqlite3
from typing import Mapping

from .captura_ptax_http import _cabecalhos
from .ptax_odata_bruta_mercados import (
    MAX_BYTES, _consulta, verificar_ptax_odata_bruta, ErroPTAXBruto,
)
from .ptax_plano import planejar_consultas_ptax
from .qualidade_mercados import _momento
from .transacoes_sqlite import savepoint_atomico


class ErroQuarentenaPTAX(ValueError):
    """Pacote de dados externos inconsistente, perigoso ou incompleto."""


ESTADO = "AMOSTRA_EXTERNA_NAO_HOMOLOGADA"
MAX_MANIFEST = 12_000
MAX_LISTA = 1000
HEADERS = frozenset({"content-type", "date", "etag", "last-modified", "content-length"})
CAMPOS = frozenset({"moeda", "consulta_url", "coletado_em", "status_http",
                    "cabecalhos_http", "raw_sha256", "fonte_declarada"})


def _json_unico(dados: bytes) -> object:
    def sem_duplicados(pares):
        saida = {}
        for k, v in pares:
            if k in saida:
                raise ErroQuarentenaPTAX("chave JSON duplicada")
            saida[k] = v
        return saida
    def invalido(v):
        raise ErroQuarentenaPTAX("JSON contém número não finito")
    try:
        return json.loads(
            dados.decode("utf-8", "strict"), parse_int=Decimal,
            parse_float=Decimal, parse_constant=invalido,
            object_pairs_hook=sem_duplicados,
        )
    except (ValueError, UnicodeDecodeError) as exc:
        if isinstance(exc, ErroQuarentenaPTAX):
            raise
        raise ErroQuarentenaPTAX("OData JSON inválido") from exc


def _vazio_odata(raw: bytes) -> bool:
    """Somente envelope vazio canônico; não interpreta HTML/WAF como vazio."""
    if not isinstance(raw, bytes) or not 1 <= len(raw) <= MAX_BYTES:
        raise ErroQuarentenaPTAX("raw ausente ou excessivo")
    doc = _json_unico(raw)
    if not isinstance(doc, dict) or "value" not in doc or (
        set(doc) - {"value", "@odata.context"}
    ) or (doc.get("@odata.context") is not None and
           not isinstance(doc.get("@odata.context"), str)):
        raise ErroQuarentenaPTAX("envelope PTAX não reconhecido")
    return doc["value"] == []


def validar_amostra_ptax(raw: bytes, manifesto: Mapping) -> dict:
    """Valida bytes, contrato e coerência temporal, sem certificar origem."""
    if not isinstance(raw, bytes) or not 1 <= len(raw) <= MAX_BYTES:
        raise ErroQuarentenaPTAX("conteúdo ausente ou acima do limite")
    if not isinstance(manifesto, Mapping) or set(manifesto) != CAMPOS:
        raise ErroQuarentenaPTAX("manifesto de captura incompleto")
    if manifesto["fonte_declarada"] != "BCB_PTAX":
        raise ErroQuarentenaPTAX("fonte declarada divergente")
    if type(manifesto["status_http"]) is not int or manifesto["status_http"] != 200:
        raise ErroQuarentenaPTAX("HTTP 200 obrigatório")
    digest = sha256(raw).hexdigest()
    if digest != manifesto["raw_sha256"]:
        raise ErroQuarentenaPTAX("SHA declarado diverge dos bytes")
    try:
        inicio, fim = _consulta(manifesto["consulta_url"], manifesto["moeda"])
        plano = planejar_consultas_ptax(
            moeda=manifesto["moeda"],
            inicio=inicio.isoformat(), fim=fim.isoformat(),
            dias_janela=(fim - inicio).days + 1,
        )[0]
        if plano["url"] != manifesto["consulta_url"]:
            raise ErroQuarentenaPTAX("URL não canônica para o plano oficial")
        coleta = _momento(manifesto["coletado_em"], "coletado_em")
        entradas = manifesto["cabecalhos_http"]
        if (not isinstance(entradas, Mapping) or
                any(not isinstance(k, str) or
                    (v is not None and not isinstance(v, str))
                    for k, v in entradas.items())):
            raise ErroQuarentenaPTAX("headers de captura inválidos")
        # Um manifesto persistido tem chaves opcionais com null; não
        # transformar null em um cabeçalho HTTP transmitido pelo provedor.
        headers = _cabecalhos({k: v for k, v in entradas.items()
                              if v is not None})
        content_length = headers.get("content-length")
        if content_length is not None and (
            not content_length.isascii() or not content_length.isdecimal()
            or int(content_length) != len(raw)
        ):
            raise ErroQuarentenaPTAX("Content-Length incompatível com bytes")
        if _vazio_odata(raw):
            status = "SEM_COTACAO_NA_RESPOSTA"
            n = 0
        else:
            r = verificar_ptax_odata_bruta(
                raw, consulta_url=manifesto["consulta_url"],
                moeda=manifesto["moeda"], coletado_em=coleta.isoformat(),
                as_of=coleta.isoformat(), raw_sha256_esperado=digest,
            )
            status = "JSON_ODATA_VERIFICADO"
            n = r["boletins_distintos"]
    except (TypeError, KeyError, ValueError, ErroPTAXBruto) as exc:
        if isinstance(exc, ErroQuarentenaPTAX):
            raise
        raise ErroQuarentenaPTAX("falha de contrato ou temporalidade PTAX") from exc
    meta = {
        "fonte_declarada": "BCB_PTAX",
        "moeda": manifesto["moeda"],
        "consulta_url": manifesto["consulta_url"],
        "coletado_em": coleta.astimezone(timezone.utc).isoformat(),
        "status_http": 200, "cabecalhos_http": {
            k: headers.get(k) for k in sorted(HEADERS)
        }, "raw_sha256": digest,
    }
    canonico = json.dumps(meta, sort_keys=True, ensure_ascii=True,
                          separators=(",", ":")).encode()
    evento = sha256(canonico).hexdigest()
    return {
        "status": ESTADO, "validacao_json": status,
        "boletins": n, "vazio": n == 0,
        "manifesto_canonico": meta, "evento_sha256": evento,
        "raw_sha256": digest, "bytes": len(raw),
        "coleta_independente_comprovada": False,
        "origem_tls_independente_comprovada": False,
        "autorizacao_operacional": False,
        "publicavel": False,
    }


def preparar_quarentena_ptax(db: sqlite3.Connection) -> None:
    db.execute("""CREATE TABLE IF NOT EXISTS nivon_ptax_quarentena_raw (
        raw_sha256 TEXT PRIMARY KEY,
        raw BLOB NOT NULL,
        bytes INTEGER NOT NULL CHECK(bytes > 0)
    )""")
    db.execute("""CREATE TABLE IF NOT EXISTS nivon_ptax_quarentena_eventos (
        evento_sha256 TEXT PRIMARY KEY,
        raw_sha256 TEXT NOT NULL
            REFERENCES nivon_ptax_quarentena_raw(raw_sha256),
        manifesto_json TEXT NOT NULL,
        qt_boletins INTEGER NOT NULL CHECK(qt_boletins >= 0),
        status TEXT NOT NULL CHECK(status = 'AMOSTRA_EXTERNA_NAO_HOMOLOGADA')
    )""")
    for nome in ("nivon_ptax_quarentena_raw", "nivon_ptax_quarentena_eventos"):
        for operacao in ("UPDATE", "DELETE"):
            db.execute(
                f"""CREATE TRIGGER IF NOT EXISTS protecao_{nome}_{operacao.lower()}
                    BEFORE {operacao} ON {nome}
                    BEGIN SELECT RAISE(ABORT, 'quarentena PTAX append-only'); END"""
            )


def receber_amostra_ptax(
    db: sqlite3.Connection, *, raw: bytes, manifesto: Mapping,
) -> dict:
    if not isinstance(db, sqlite3.Connection):
        raise ErroQuarentenaPTAX("SQLite obrigatório")
    validacao = validar_amostra_ptax(raw, manifesto)
    preparar_quarentena_ptax(db)
    m = json.dumps(validacao["manifesto_canonico"], ensure_ascii=True,
                   sort_keys=True, separators=(",", ":"))
    with savepoint_atomico(db):
        row = db.execute(
            "SELECT raw,bytes FROM nivon_ptax_quarentena_raw WHERE raw_sha256=?",
            (validacao["raw_sha256"],),
        ).fetchone()
        if row is None:
            db.execute(
                "INSERT INTO nivon_ptax_quarentena_raw VALUES(?,?,?)",
                (validacao["raw_sha256"], raw, len(raw)),
            )
        elif row[0] != raw or row[1] != len(raw):
            raise ErroQuarentenaPTAX("colisão ou alteração de raw")
        event = db.execute(
            "SELECT manifesto_json,qt_boletins "
            "FROM nivon_ptax_quarentena_eventos WHERE evento_sha256=?",
            (validacao["evento_sha256"],),
        ).fetchone()
        if event is None:
            db.execute(
                "INSERT INTO nivon_ptax_quarentena_eventos VALUES(?,?,?,?,?)",
                (validacao["evento_sha256"], validacao["raw_sha256"],
                 m, validacao["boletins"], ESTADO),
            )
        elif tuple(event) != (m, validacao["boletins"]):
            raise ErroQuarentenaPTAX("evento repetido com metadados divergentes")
    return {
        **{k: validacao[k] for k in (
            "status", "validacao_json", "boletins", "vazio",
            "evento_sha256", "raw_sha256", "bytes", "publicavel"
        )},
        "nova_versao": event is None,
        "aprovado_para_ledger_operacional": False,
    }


def listar_amostras_ptax(
    db: sqlite3.Connection, *, limite: int = 100,
) -> list[dict]:
    if not isinstance(db, sqlite3.Connection) or type(limite) is not int or (
        not 1 <= limite <= MAX_LISTA
    ):
        raise ErroQuarentenaPTAX("consulta inválida")
    try:
        eventos = db.execute(
            "SELECT evento_sha256,raw_sha256,manifesto_json,qt_boletins "
            "FROM nivon_ptax_quarentena_eventos "
            "ORDER BY evento_sha256 LIMIT ?",
            (limite,),
        ).fetchall()
    except sqlite3.Error:
        return []
    res = []
    for eid, digest, meta, quantidade in eventos:
        row = db.execute(
            "SELECT raw,bytes FROM nivon_ptax_quarentena_raw WHERE raw_sha256=?",
            (digest,),
        ).fetchone()
        if row is None or sha256(row[0]).hexdigest() != digest or (
            row[1] != len(row[0])
        ):
            raise ErroQuarentenaPTAX("raw de quarentena corrompido")
        try:
            doc = json.loads(meta)
            v = validar_amostra_ptax(row[0], doc)
        except (TypeError, ValueError) as exc:
            raise ErroQuarentenaPTAX("manifesto de quarentena corrompido") from exc
        if v["evento_sha256"] != eid or v["boletins"] != quantidade:
            raise ErroQuarentenaPTAX("evento ou quantidade divergentes")
        res.append({
            "evento_sha256": eid,
            "raw_sha256": digest,
            "boletins": quantidade,
            "coletado_em": doc["coletado_em"],
            "moeda": doc["moeda"],
            "aprovado_para_ledger_operacional": False,
            "publicavel": False,
        })
    return res
