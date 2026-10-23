"""Gate offline de autorização por edição para a outbox.

O documento é assinado fora deste módulo por um aprovador independente.
Uma assinatura HMAC válida garante integridade do documento, mas NÃO comprova
que direitos, consentimento ou revisão ocorreram de fato. A autoridade e
segregação da chave exigem auditoria operacional separada.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import re
from datetime import datetime, timedelta, timezone

CAMPOS = frozenset({
    "idempotency_key", "edicao", "payload_sha256", "sha256_editorial",
    "destinatario_hmac", "revisao_editorial_id", "direitos_publicacao_id",
    "consentimento_id", "template_aprovado_id", "orcamento_id",
    "aprovador_id", "emitido_em", "valido_ate",
    "revisao_independente", "direitos_publicacao", "consentimento_ativo",
    "template_aprovado", "orcamento_aprovado", "revogado",
})
IDS = ("revisao_editorial_id", "direitos_publicacao_id", "consentimento_id",
       "template_aprovado_id", "orcamento_id", "aprovador_id")
FLAGS = ("revisao_independente", "direitos_publicacao", "consentimento_ativo",
         "template_aprovado", "orcamento_aprovado")
_SHA = re.compile(r"^[a-f0-9]{64}$")
_IDENT = re.compile(r"^[A-Za-z0-9._:-]{12,128}$")


class ErroAutorizacaoEnvio(ValueError):
    pass


def _tempo(v: object) -> datetime:
    if not isinstance(v, str) or "T" not in v:
        raise ErroAutorizacaoEnvio("autorização requer hora e fuso")
    try:
        d = datetime.fromisoformat(v.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ErroAutorizacaoEnvio("timestamp inválido") from exc
    if d.tzinfo is None or d.utcoffset() is None:
        raise ErroAutorizacaoEnvio("autorização sem fuso")
    return d.astimezone(timezone.utc)


def conteudo_canonico(documento: dict) -> bytes:
    """Serialização pública para assinatura feita fora deste módulo."""
    if not isinstance(documento, dict) or set(documento) != CAMPOS:
        raise ErroAutorizacaoEnvio("campos do documento de aprovação incompletos ou extras")
    return json.dumps(documento, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=False, allow_nan=False).encode("utf-8")


def verificar_autorizacao(documento: dict, assinatura: str, *,
                          chave_auditoria: bytes, agora: datetime | None = None) -> str:
    """Verifica integridade/escopo e validade, sem conceder direitos por si só."""
    if not isinstance(chave_auditoria, bytes) or len(chave_auditoria) < 32:
        raise ErroAutorizacaoEnvio("chave do aprovador ausente ou curta")
    raw = conteudo_canonico(documento)
    if len(raw) > 6000:
        raise ErroAutorizacaoEnvio("autorização excessiva")
    if not isinstance(assinatura, str) or not re.fullmatch(r"sha256=[0-9a-f]{64}", assinatura):
        raise PermissionError("assinatura de aprovação ausente")
    esperado = "sha256=" + hmac.new(chave_auditoria, raw, hashlib.sha256).hexdigest()
    if not hmac.compare_digest(assinatura, esperado):
        raise PermissionError("assinatura de aprovação não corresponde ao documento")
    for campo in ("idempotency_key", "payload_sha256", "sha256_editorial",
                  "destinatario_hmac"):
        if not isinstance(documento[campo], str) or not _SHA.fullmatch(documento[campo]):
            raise ErroAutorizacaoEnvio("hash de vinculação inválido: " + campo)
    if not isinstance(documento["edicao"], str) or not re.fullmatch(
            r"\d{4}-\d{2}-\d{2}", documento["edicao"]):
        raise ErroAutorizacaoEnvio("data da edição inválida")
    try:
        datetime.strptime(documento["edicao"], "%Y-%m-%d")
    except ValueError as exc:
        raise ErroAutorizacaoEnvio("data da edição inexistente") from exc
    for campo in IDS:
        if not isinstance(documento[campo], str) or not _IDENT.fullmatch(documento[campo]):
            raise ErroAutorizacaoEnvio("evidência de aprovação inválida: " + campo)
    if any(documento[campo] is not True for campo in FLAGS) or documento["revogado"] is not False:
        raise PermissionError("aprovação, consentimento, direitos ou orçamento não demonstrados")
    emitido = _tempo(documento["emitido_em"])
    ate = _tempo(documento["valido_ate"])
    instante = agora if agora is not None else datetime.now(timezone.utc)
    if instante.tzinfo is None:
        raise ErroAutorizacaoEnvio("relógio de validação sem fuso")
    instante = instante.astimezone(timezone.utc)
    if not (emitido <= instante < ate <= emitido + timedelta(hours=24)):
        raise PermissionError("aprovação expirada, futura ou acima de 24 horas")
    return hashlib.sha256(raw).hexdigest()
