"""Cadastro transacional de emissores autorizados da outbox NIVON.

Separação: o registry guarda APENAS fingerprints SHA-256, nunca chaves
secretas. Um operador administrador assina as operações de provisionamento
e revogação fora da rotina de despacho. NÃO consulta rede.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import re
import sqlite3
from datetime import datetime, timezone

from .provas_externas_envio import TIPOS

_ID = re.compile(r"^[A-Za-z0-9_.:-]{12,128}$")
_SHA = re.compile(r"^[0-9a-f]{64}$")


class ErroRegistry(ValueError):
    pass


def _esquema(con: sqlite3.Connection) -> None:
    if con.in_transaction:
        raise ErroRegistry("registry exige conexão fora de transação ao criar schema")
    con.execute("""CREATE TABLE IF NOT EXISTS nivon_registry_root (
        id INTEGER PRIMARY KEY CHECK (id=1), root_fingerprint TEXT NOT NULL,
        manifesto_sha256 TEXT NOT NULL, criado_em TEXT NOT NULL)""")
    con.execute("""CREATE TABLE IF NOT EXISTS nivon_registry_emissores (
        emissor_id TEXT PRIMARY KEY,
        tipo TEXT NOT NULL UNIQUE,
        key_fingerprint TEXT NOT NULL UNIQUE,
        revogado_em TEXT, evidencia_revogacao_sha256 TEXT,
        criado_em TEXT NOT NULL)""")


def _agora() -> str:
    return datetime.now(timezone.utc).isoformat()


def _root(root: bytes) -> None:
    if not isinstance(root, bytes) or len(root) < 32:
        raise ErroRegistry("chave raiz administrativa insuficiente")


def _canonico(obj: dict) -> bytes:
    if not isinstance(obj, dict):
        raise ErroRegistry("manifesto administrativo inválido")
    return json.dumps(obj, ensure_ascii=False, sort_keys=True,
                      separators=(",", ":"), allow_nan=False).encode("utf-8")


def _autenticar(obj: dict, assinatura: str, root: bytes) -> str:
    _root(root)
    raw = _canonico(obj)
    if len(raw) > 6000:
        raise ErroRegistry("manifesto administrativo excessivo")
    if not isinstance(assinatura, str) or not re.fullmatch("sha256=[0-9a-f]{64}", assinatura):
        raise PermissionError("assinatura administrativa ausente")
    esperado = "sha256=" + hmac.new(root, raw, hashlib.sha256).hexdigest()
    if not hmac.compare_digest(assinatura, esperado):
        raise PermissionError("assinatura administrativa não corresponde")
    return hashlib.sha256(raw).hexdigest()


def provisionar_registro(con: sqlite3.Connection, *, manifesto: dict,
                        assinatura: str, chave_raiz: bytes) -> dict:
    """Apenas primeira instalação, fail-closed em bases já provisionadas.

    Manifesto assinado contém fingerprints, não chaves.
    A autoridade da chave raiz deve ser estabelecida externamente.
    """
    digest = _autenticar(manifesto, assinatura, chave_raiz)
    if set(manifesto) != {"operacao", "versao", "emissores"} or (
            manifesto["operacao"] != "PROVISIONAR" or manifesto["versao"] != 1):
        raise ErroRegistry("operação/versão administrativa inválida")
    registros = manifesto["emissores"]
    if not isinstance(registros, list) or len(registros) != len(TIPOS):
        raise ErroRegistry("manifesto deve conter cinco emissores")
    ids, tipos, fps = set(), set(), set()
    for item in registros:
        if not isinstance(item, dict) or set(item) != {
                "emissor_id", "tipo", "key_fingerprint"}:
            raise ErroRegistry("campos do emissor inválidos")
        nome, tipo, fp = item["emissor_id"], item["tipo"], item["key_fingerprint"]
        if (not isinstance(nome, str) or not _ID.fullmatch(nome)
                or tipo not in TIPOS or not isinstance(fp, str)
                or not _SHA.fullmatch(fp) or nome in ids or tipo in tipos or fp in fps
                or fp == hashlib.sha256(chave_raiz).hexdigest()):
            raise ErroRegistry("emissor duplicado, desconhecido ou chave inválida")
        ids.add(nome);tipos.add(tipo);fps.add(fp)
    if tipos != set(TIPOS):
        raise ErroRegistry("tipos de autoridades incompletos")
    _esquema(con)
    con.execute("BEGIN IMMEDIATE")
    try:
        if con.execute("SELECT 1 FROM nivon_registry_root WHERE id=1").fetchone():
            raise PermissionError("registry já provisionado; não substituir manifesto")
        if con.execute("SELECT 1 FROM nivon_registry_emissores LIMIT 1").fetchone():
            raise PermissionError("registry legado inconsistente; requer migração")
        now = _agora()
        con.execute("""INSERT INTO nivon_registry_root
            (id,root_fingerprint,manifesto_sha256,criado_em) VALUES (1,?,?,?)""",
                    (hashlib.sha256(chave_raiz).hexdigest(), digest, now))
        con.executemany("""INSERT INTO nivon_registry_emissores
            (emissor_id,tipo,key_fingerprint,criado_em)
            VALUES (?,?,?,?)""", [(x["emissor_id"], x["tipo"],
                                   x["key_fingerprint"], now) for x in registros])
        con.commit()
    except Exception:
        con.rollback()
        raise
    return {"estado": "REGISTRY_PROVISIONADO_OFFLINE", "emissores": len(registros),
            "manifesto_sha256": digest}


def revogar_emissor(con: sqlite3.Connection, *, evento: dict,
                   assinatura: str, chave_raiz: bytes) -> dict:
    """Revogação permanente assinada; não altera envios já reservados."""
    digest = _autenticar(evento, assinatura, chave_raiz)
    if set(evento) != {"operacao", "emissor_id", "evidencia_id"} or (
            evento["operacao"] != "REVOGAR"
            or not isinstance(evento["emissor_id"], str)
            or not _ID.fullmatch(evento["emissor_id"])
            or not isinstance(evento["evidencia_id"], str)
            or not _ID.fullmatch(evento["evidencia_id"])):
        raise ErroRegistry("evento de revogação inválido")
    _esquema(con)
    con.execute("BEGIN IMMEDIATE")
    try:
        root = con.execute(
            "SELECT root_fingerprint FROM nivon_registry_root WHERE id=1").fetchone()
        if not root or not hmac.compare_digest(
                root[0], hashlib.sha256(chave_raiz).hexdigest()):
            raise PermissionError("chave raiz diferente da primeira instalação")
        registro = con.execute("""SELECT revogado_em FROM nivon_registry_emissores
            WHERE emissor_id=?""", (evento["emissor_id"],)).fetchone()
        if not registro:
            raise ErroRegistry("emissor não cadastrado")
        if registro[0] is not None:
            raise PermissionError("emissor já revogado; não sobrescrever histórico")
        con.execute("""UPDATE nivon_registry_emissores
            SET revogado_em=?,evidencia_revogacao_sha256=?
            WHERE emissor_id=?""", (_agora(), digest, evento["emissor_id"]))
        con.commit()
    except Exception:
        con.rollback()
        raise
    return {"emissor_id": evento["emissor_id"], "estado": "REVOGADO",
            "evento_sha256": digest}


def emissores_confiaveis(con: sqlite3.Connection, chaves_fornecidas: dict) -> dict:
    """Resolve chaves fornecidas somente se estiverem ancoradas no SQLite.

    Requer transação de escrita (BEGIN IMMEDIATE) para impedir revogação
    concorrente entre a verificação e a reserva.
    """
    if not con.in_transaction:
        raise ErroRegistry("registry deve ser consultado sob transação")
    if not isinstance(chaves_fornecidas, dict):
        raise PermissionError("chaves de emissores não fornecidas")
    root = con.execute("SELECT manifesto_sha256 FROM nivon_registry_root WHERE id=1").fetchone()
    rows = con.execute("""SELECT emissor_id,tipo,key_fingerprint,revogado_em
        FROM nivon_registry_emissores""").fetchall()
    if root is None or len(rows) != len(TIPOS) or set(chaves_fornecidas) != {
            r[0] for r in rows}:
        raise PermissionError("registry não provisionado ou chaves incompletas")
    resultado = {}
    for nome, tipo, fp, revogado in rows:
        info = chaves_fornecidas.get(nome)
        if (revogado is not None or tipo not in TIPOS
                or not isinstance(info, dict)
                or set(info) != {"tipo", "chave", "ativo"}
                or info["tipo"] != tipo or info["ativo"] is not True
                or not isinstance(info["chave"], bytes)
                or not hmac.compare_digest(hashlib.sha256(info["chave"]).hexdigest(), fp)):
            raise PermissionError("emissor revogado, chave divergente ou não confiável")
        resultado[nome] = info
    return resultado


def resumo_registry(con: sqlite3.Connection) -> dict:
    """Diagnóstico sem chaves nem IDs de consentimento."""
    _esquema(con)
    dados = con.execute("""SELECT tipo,revogado_em FROM
        nivon_registry_emissores ORDER BY tipo""").fetchall()
    ativo = sum(rev is None for _, rev in dados)
    return {
        "provisionado": bool(con.execute("SELECT 1 FROM nivon_registry_root").fetchone()),
        "total": len(dados), "ativos": ativo,
        "revogados": len(dados) - ativo,
        "apto_registry": len(dados) == len(TIPOS) and ativo == len(TIPOS),
    }
