"""Verificação OFFLINE de recibo MAC para âncora do ledger de previsões.

O emissor HMAC deve operar em domínio de confiança distinto do SQLite.
MAC com chave simétrica confere integridade/autoria relativa à posse da
chave; NÃO comprova que a âncora foi gravada num storage remoto/WORM,
nem fornece timestamp qualificado. A função NÃO assina recibos.
"""
from __future__ import annotations

from datetime import timezone
from hashlib import sha256
import hmac
import json
import sqlite3
from typing import Mapping

from .ledger_previsoes_mercado import consultar_ledger
from .proveniencia_previsoes_mercado import _hash, _hora, _texto


class ErroAncoraMercado(ValueError):
    """Recibo ausente, adulterado, incompatível ou não verificável."""


RECEIPT_VERSION = "NIVON_LEDGER_ANCHOR_V1"
CAMPOS_RECIBO = frozenset({
    "versao", "ledger_id", "emissor_id", "localizacao_externa_id",
    "sequencia", "cabeca_sha256", "ancorado_em", "nonce_hex", "mac_sha256",
})


def _canonico(obj: dict) -> bytes:
    return json.dumps(obj, ensure_ascii=True, sort_keys=True,
                      separators=(",", ":"), allow_nan=False).encode("utf-8")


def verificar_recibo_ancora(
    recibo: Mapping, *, ledger_id: str, segredo_verificacao: bytes,
    as_of: str,
) -> dict:
    """Valida envelope e HMAC; não acessa URL, signer, object-store ou rede.

    segredo_verificacao é compartilhado com assinador independente. NÃO
    armazene a chave simétrica junto ao ledger. A assinatura é um mecanismo
    opt-in de defesa; não substitui WORM nem assinatura assimétrica.
    """
    try:
        corte = _hora(as_of, "as_of")
        _texto(ledger_id, "ledger_id")
        if (not isinstance(segredo_verificacao, bytes) or
                len(segredo_verificacao) < 32):
            raise ErroAncoraMercado("chave de verificação inválida")
        if not isinstance(recibo, Mapping) or set(recibo) != CAMPOS_RECIBO:
            raise ErroAncoraMercado("schema de recibo inválido")
        r = dict(recibo)
        if r["versao"] != RECEIPT_VERSION or r["ledger_id"] != ledger_id:
            raise ErroAncoraMercado("domínio de âncora incompatível")
        _texto(r["emissor_id"], "emissor_id")
        _texto(r["localizacao_externa_id"], "localizacao_externa_id")
        _hash(r["cabeca_sha256"], "cabeca_sha256")
        if type(r["sequencia"]) is not int or not 1 <= r["sequencia"] <= 10000:
            raise ErroAncoraMercado("sequência inválida")
        instante = _hora(r["ancorado_em"], "ancorado_em")
        if instante > corte:
            raise ErroAncoraMercado("recibo posterior ao corte")
        nonce = r["nonce_hex"]
        if (not isinstance(nonce, str) or len(nonce) != 32 or
                any(c not in "0123456789abcdef" for c in nonce)):
            raise ErroAncoraMercado("nonce inválido")
        mac = _hash(r["mac_sha256"], "mac_sha256")
        corpo = {k: v for k, v in r.items() if k != "mac_sha256"}
        esperado = hmac.new(segredo_verificacao, _canonico(corpo),
                            sha256).hexdigest()
        if not hmac.compare_digest(esperado, mac):
            raise ErroAncoraMercado("MAC inválido ou chave não corresponde")
        return {
            "status": "MAC_RECIBO_VALIDADO_OFFLINE",
            "ledger_id": ledger_id,
            "sequencia": r["sequencia"],
            "cabeca_sha256": r["cabeca_sha256"],
            "emissor_id": r["emissor_id"],
            "mac_conferido": True,
            "armazenamento_externo_comprovado": False,
            "timestamp_independente_comprovado": False,
            "publicavel": False,
        }
    except (ValueError, TypeError) as exc:
        if isinstance(exc, ErroAncoraMercado):
            raise
        raise ErroAncoraMercado("recibo ou campo inválido") from exc


def auditar_ledger_com_recibo(
    con: sqlite3.Connection, *, recibo: Mapping, ledger_id: str,
    segredo_verificacao: bytes, as_of: str,
) -> dict:
    """Compara cabeça e comprimento do SQLite contra recibo MAC válido.

    A avaliação de validade de chave, fonte de horário e armazenamento
    externo de fato ocorre fora deste componente.
    """
    prova = verificar_recibo_ancora(
        recibo, ledger_id=ledger_id,
        segredo_verificacao=segredo_verificacao, as_of=as_of,
    )
    try:
        ledger = consultar_ledger(
            con, cabeca_esperada_sha256=prova["cabeca_sha256"]
        )
    except (ValueError, sqlite3.Error) as exc:
        raise ErroAncoraMercado("ledger não corresponde à âncora") from exc
    if ledger.get("quantidade") != prova["sequencia"]:
        raise ErroAncoraMercado("sequência do ledger não coincide com recibo")
    ultimo = ledger["registros"][-1]["previsao"]
    if _hora(recibo["ancorado_em"], "ancorado_em") < _hora(
        ultimo["registrado_em"], "registrado_em"
    ):
        raise ErroAncoraMercado("recibo anterior ao registro final do ledger")
    return {**prova, "status": "LEDGER_E_MAC_CONFERIDOS_OFFLINE"}
