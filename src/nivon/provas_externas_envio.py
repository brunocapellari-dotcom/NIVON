"""Verificação offline de provas emitidas por autoridades distintas.

Um comprovante autodeclarado não equivale a registro externo verificado.
Emissores e chaves devem vir de configuração confiável externa.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import re
from datetime import datetime, timezone

from .autorizacao_envio import _tempo

TIPOS = {
    "REVISAO_EDITORIAL": "revisao_editorial_id",
    "DIREITOS_PUBLICACAO": "direitos_publicacao_id",
    "CONSENTIMENTO": "consentimento_id",
    "TEMPLATE": "template_aprovado_id",
    "ORCAMENTO": "orcamento_id",
}
CAMPOS_PROVA = frozenset({
    "tipo", "evidencia_id", "emissor_id", "edicao", "idempotency_key",
    "sha256_editorial", "destinatario_hmac", "payload_sha256",
    "emitido_em", "valido_ate", "estado",
})
ID = re.compile(r"^[A-Za-z0-9_.:-]{12,128}$")
SHA = re.compile(r"^[a-f0-9]{64}$")


class ErroProvaExterna(ValueError):
    pass


def canonicalizar_prova(prova: dict) -> bytes:
    """Bytes a serem assinados por um emissor independente."""
    if not isinstance(prova, dict) or set(prova) != CAMPOS_PROVA:
        raise ErroProvaExterna("campos do comprovante externo inválidos")
    return json.dumps(prova, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=False, allow_nan=False).encode("utf-8")


def verificar_pacote_externo(documento: dict, comprovantes: list[dict],
                            emissores: dict, *, chave_auditoria: bytes,
                            agora: datetime | None = None) -> str:
    """Hash de cinco provas assinadas vinculadas à edição.

    O registro de confiança é externo, separado dos payloads do documento.
    A função não descobre ou aprova automaticamente qualquer emissor.
    """
    if not isinstance(documento, dict) or not isinstance(comprovantes, list):
        raise ErroProvaExterna("pacote de evidências externas ausente")
    if len(comprovantes) != len(TIPOS) or not isinstance(emissores, dict):
        raise PermissionError("cinco comprovantes independentes obrigatórios")
    agora = agora or datetime.now(timezone.utc)
    if agora.tzinfo is None:
        raise ErroProvaExterna("relógio sem fuso")
    agora = agora.astimezone(timezone.utc)
    visto_tipos, visto_emissores, visto_chaves = set(), set(), set()
    identidades = []
    for item in comprovantes:
        if not isinstance(item, dict) or set(item) != CAMPOS_PROVA | {"assinatura"}:
            raise ErroProvaExterna("comprovante assinado com schema inválido")
        prova = {k: item[k] for k in CAMPOS_PROVA}
        raw = canonicalizar_prova(prova)
        if len(raw) > 4000:
            raise ErroProvaExterna("comprovante excessivo")
        tipo = prova["tipo"]
        if tipo not in TIPOS or tipo in visto_tipos:
            raise PermissionError("tipo de comprovante faltante ou duplicado")
        emissor_id = prova["emissor_id"]
        if not isinstance(emissor_id, str) or not ID.fullmatch(emissor_id):
            raise ErroProvaExterna("identidade do emissor inválida")
        autorizado = emissores.get(emissor_id)
        if not isinstance(autorizado, dict) or set(autorizado) != {"tipo", "chave", "ativo"}:
            raise PermissionError("emissor externo não confiável")
        chave = autorizado["chave"]
        if (autorizado["tipo"] != tipo or autorizado["ativo"] is not True
                or not isinstance(chave, bytes) or len(chave) < 32):
            raise PermissionError("emissor não autorizado para o tipo da prova")
        fp = hashlib.sha256(chave).hexdigest()
        if (emissor_id in visto_emissores or fp in visto_chaves
                or hmac.compare_digest(chave, chave_auditoria)):
            raise PermissionError("emissores e aprovador devem ser independentes")
        sig = item["assinatura"]
        esperado = "sha256=" + hmac.new(chave, raw, hashlib.sha256).hexdigest()
        if not isinstance(sig, str) or not hmac.compare_digest(sig, esperado):
            raise PermissionError("assinatura de comprovante externo inválida")
        if (prova["evidencia_id"] != documento[TIPOS[tipo]]
                or not isinstance(prova["evidencia_id"], str)
                or not ID.fullmatch(prova["evidencia_id"])):
            raise PermissionError("ID de evidência diverge da autorização")
        for k in ("edicao", "idempotency_key", "sha256_editorial",
                  "destinatario_hmac", "payload_sha256"):
            if prova[k] != documento[k]:
                raise PermissionError("escopo externo diverge: " + k)
        for k in ("idempotency_key", "sha256_editorial", "destinatario_hmac",
                  "payload_sha256"):
            if not SHA.fullmatch(prova[k]):
                raise ErroProvaExterna("hash externo inválido")
        if prova["estado"] != "APROVADA":
            raise PermissionError("evidência revogada ou não aprovada")
        inicio = _tempo(prova["emitido_em"])
        fim = _tempo(prova["valido_ate"])
        doc_expira = _tempo(documento["valido_ate"])
        if not (inicio <= agora < fim <= doc_expira):
            raise PermissionError("prova externa futura, vencida ou fora da autorização")
        visto_tipos.add(tipo)
        visto_emissores.add(emissor_id)
        visto_chaves.add(fp)
        identidades.append((tipo, hashlib.sha256(raw).hexdigest(), sig))
    if visto_tipos != set(TIPOS):
        raise PermissionError("faltam comprovantes obrigatórios")
    bruto = json.dumps(sorted(identidades), separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(bruto).hexdigest()
