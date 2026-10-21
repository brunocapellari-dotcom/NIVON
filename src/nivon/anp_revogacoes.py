"""Revogações autenticadas de aprovações ANP/LPC; aplicação offline.

Eventos de revogação são assinados por autoridade diferente dos dois
revisores iniciais e recebidos pelo controlador, nunca por campos do XLSX.
O contrato preserva conhecimento point-in-time: o bloqueio vigora após
recebimento confiável da revogação, sem reescrever consultas pretéritas.

Não implementa emissão de assinatura, KMS, distribuição ou sincronização
externa de listas: sem isso não existe prontidão para produção.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from hashlib import sha256
import hmac
import json
import re
import sqlite3
from typing import Mapping

_DOMINIOS = frozenset({"DIREITOS_USO", "HOMOLOGACAO_LAYOUT"})
_SHA = re.compile(r"^[0-9a-f]{64}$")
_ID = re.compile(r"^[a-zA-Z0-9_.:-]{8,120}$")
_PREFIX = b"NIVON_ANP_LPC_REVOGACAO_V1\x00"
_MOTIVOS = frozenset({
    "DIREITOS_INVALIDADOS", "EVIDENCIA_INVALIDA",
    "ERRO_DE_LAYOUT", "CHAVE_COMPROMETIDA", "REVISAO_REQUERIDA",
})


class ErroRevogacaoANP(PermissionError):
    pass


def _instante(v: object, nome: str) -> datetime:
    if not isinstance(v, str):
        raise ErroRevogacaoANP(f"{nome}: timestamp timezone obrigatório")
    try:
        x = datetime.fromisoformat(v.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ErroRevogacaoANP(f"{nome}: timestamp inválido") from exc
    if x.tzinfo is None or x.utcoffset() is None:
        raise ErroRevogacaoANP(f"{nome}: timezone obrigatório")
    return x.astimezone(timezone.utc)


def registrar_revogacao_anp(
    db: sqlite3.Connection, *, documento: Mapping,
    autoridade: Mapping, recebido_em_confiavel: str,
) -> dict:
    """Revogação vinculada à atestação armazenada, idempotente e auditável.

    O controlador externo garante que "autoridade" e "recebido_em_confiavel"
    não sejam fornecidos por um coletor não confiável. Aqui apenas se verifica
    o contrato formal. Uma aprovação revogada não pode voltar a ser usada.
    """
    if not isinstance(documento, Mapping) or set(documento) != {
        "versao", "revogacao_id", "edicao_sha256", "dominio_alvo",
        "aprovacao_id", "emissor_id", "motivo_codigo", "emitido_em",
        "assinatura_hmac_sha256",
    }:
        raise ErroRevogacaoANP("schema de revogação inválido")
    if (not isinstance(autoridade, Mapping)
            or set(autoridade) != {"chave", "emissor"}
            or not isinstance(autoridade["chave"], bytes)
            or len(autoridade["chave"]) < 32
            or not isinstance(autoridade["emissor"], str)
            or not autoridade["emissor"].strip()):
        raise ErroRevogacaoANP("autoridade de revogação confiável ausente")
    if (type(documento["versao"]) is not int
            or documento["versao"] != 1
            or documento["emissor_id"] != autoridade["emissor"]
            or documento["dominio_alvo"] not in _DOMINIOS
            or documento["motivo_codigo"] not in _MOTIVOS):
        raise ErroRevogacaoANP("autoridade, domínio ou motivo inválido")
    rid, aid = documento["revogacao_id"], documento["aprovacao_id"]
    sha = documento["edicao_sha256"]
    if (not isinstance(rid, str) or not _ID.fullmatch(rid)
            or not isinstance(aid, str) or not _ID.fullmatch(aid)
            or not isinstance(sha, str) or not _SHA.fullmatch(sha)):
        raise ErroRevogacaoANP("ID de revogação/aprovação ou SHA de edição inválido")
    signature = documento["assinatura_hmac_sha256"]
    if not isinstance(signature, str) or not _SHA.fullmatch(signature):
        raise ErroRevogacaoANP("assinatura de revogação ausente")
    unsigned = {k: v for k, v in documento.items() if k != "assinatura_hmac_sha256"}
    try:
        canonical = json.dumps(unsigned, sort_keys=True, ensure_ascii=True,
                               separators=(",", ":"), allow_nan=False).encode()
    except (ValueError, TypeError, OverflowError) as exc:
        raise ErroRevogacaoANP("revogação não é JSON determinístico") from exc
    expected = hmac.new(autoridade["chave"], _PREFIX + canonical, sha256).hexdigest()
    if not hmac.compare_digest(signature, expected):
        raise ErroRevogacaoANP("assinatura de revogação não autenticada")
    emitido = _instante(documento["emitido_em"], "emitido_em")
    recebido = _instante(recebido_em_confiavel, "recebido_em_confiavel")
    if not emitido <= recebido <= emitido + timedelta(hours=48):
        raise ErroRevogacaoANP("tempo de revogação futuro, tardio ou inconsistente")

    db.row_factory = sqlite3.Row
    with db:
        aprovacao = db.execute(
            """SELECT a.aprovacao_id, a.emissor_id, e.classe,
                      (SELECT MIN(c.data_coleta) FROM anp_semanal_capturas c
                       WHERE c.sha=e.sha) AS primeira_coleta
               FROM anp_semanal_atestacoes a
               JOIN anp_semanal_edicoes e ON e.sha=a.sha
               WHERE a.sha=? AND a.dominio=?""",
            (sha, documento["dominio_alvo"]),
        ).fetchone()
        if (aprovacao is None or aprovacao["aprovacao_id"] != aid
                or aprovacao["classe"] != "REAL_AUTORIZADO"):
            raise ErroRevogacaoANP("aprovação alvo ausente ou não autorizada")
        if aprovacao["primeira_coleta"] is None or recebido.isoformat() < aprovacao["primeira_coleta"]:
            raise ErroRevogacaoANP("revogação recebida antes da primeira captura")
        emissores = {
            x["emissor_id"] for x in db.execute(
                "SELECT emissor_id FROM anp_semanal_atestacoes WHERE sha=?", (sha,)
            ).fetchall()
        }
        if autoridade["emissor"] in emissores:
            raise ErroRevogacaoANP("autoridade de revogação não pode ser revisor inicial")
        assinatura_sha = sha256(signature.encode("ascii")).hexdigest()
        dados = (
            rid, sha, documento["dominio_alvo"], aid, autoridade["emissor"],
            documento["motivo_codigo"], emitido.isoformat(),
            recebido.isoformat(), assinatura_sha,
        )
        anterior = db.execute(
            "SELECT * FROM anp_semanal_revogacoes WHERE revogacao_id=?", (rid,)
        ).fetchone()
        if anterior is not None:
            cols = ("revogacao_id", "sha", "dominio", "aprovacao_id",
                    "emissor_id", "motivo_codigo", "emitido_em",
                    "recebido_em", "assinatura_sha256")
            if tuple(anterior[c] for c in cols) != dados:
                raise ErroRevogacaoANP("revogação duplicada com dados conflitantes")
            novo = False
        else:
            # Não admitir declaração retroativa ou duplicada de aprovação.
            # A linha é preservada (sem UPDATE/DELETE na API).
            db.execute("""INSERT INTO anp_semanal_revogacoes
                (revogacao_id,sha,dominio,aprovacao_id,emissor_id,motivo_codigo,
                 emitido_em,recebido_em,assinatura_sha256)
                VALUES (?,?,?,?,?,?,?,?,?)""", dados)
            novo = True
    return {
        "status": "APROVACAO_REVOGADA_POR_EVIDENCIA_AUTENTICADA",
        "revogacao_id": rid, "edicao_sha256": sha,
        "dominio": documento["dominio_alvo"], "motivo_codigo": documento["motivo_codigo"],
        "recebido_em": recebido.isoformat(), "registro_novo": novo,
        "publicavel": False, "revogacao_distribuida": False,
    }
