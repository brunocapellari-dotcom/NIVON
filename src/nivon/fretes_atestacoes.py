"""Verificação offline e fail-closed de atestações comerciais de fretes.

Uma declaração de status e um SHA textual não são evidência
autenticada. Verifica HMAC de agentes autorizadores independentes, tempo e
vínculo com o conteúdo exato do evento. Não assina, emite ou aprova direitos.

HMAC é contrato de teste/protótipo offline; rotação, custódia das chaves,
revogação e trilha do atestador dependem de serviço confiável homologado.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from hashlib import sha256
import hmac
import json
import re
from typing import Mapping


class ErroAtestacaoFrete(ValueError):
    pass


_SHA = re.compile(r"^[0-9a-f]{64}$")
_UTC = timezone.utc


def serializacao_canonica(obj: Mapping) -> bytes:
    if not isinstance(obj, Mapping) or not all(isinstance(k, str) for k in obj):
        raise ErroAtestacaoFrete("objeto de evidência inválido")
    try:
        return json.dumps(obj, sort_keys=True, ensure_ascii=True,
                          separators=(",", ":"), allow_nan=False).encode("utf-8")
    except (TypeError, ValueError, OverflowError) as exc:
        raise ErroAtestacaoFrete("evidência não é JSON determinístico") from exc


def hash_evento(evento: Mapping) -> str:
    """Hash de todo envelope, inclusive campos não reutilizados na análise."""
    return sha256(serializacao_canonica(evento)).hexdigest()


def _instante(v: object, campo: str) -> datetime:
    if not isinstance(v, str):
        raise ErroAtestacaoFrete(f"{campo}: timestamp não informado")
    try:
        dt = datetime.fromisoformat(v.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ErroAtestacaoFrete(f"{campo}: timestamp inválido") from exc
    if dt.tzinfo is None or dt.utcoffset() is None:
        raise ErroAtestacaoFrete(f"{campo}: timezone obrigatório")
    return dt.astimezone(_UTC)


def verificar_atestacao(
    atestacao: Mapping, *, dominio: str, chave_confiavel: bytes,
    emissor_esperado: str, recebido_em: datetime,
    max_dias_validade: int = 7,
) -> None:
    """HMAC cobre TODOS os campos sem assinatura, inclusive versão e expiração.

    O tempo de recepção é entrada do canal confiável. A assinatura não
    comprova revogação posterior, autenticidade do RAW ou licença externa.
    """
    if dominio not in {"DIREITOS", "RESOLUCAO"}:
        raise ErroAtestacaoFrete("domínio de atestação inválido")
    if (not isinstance(chave_confiavel, bytes) or len(chave_confiavel) < 32
            or not isinstance(emissor_esperado, str) or not emissor_esperado
            or type(max_dias_validade) is not int or not 1 <= max_dias_validade <= 90):
        raise ErroAtestacaoFrete("configuração confiável de atestação ausente")
    if not isinstance(recebido_em, datetime) or recebido_em.tzinfo is None or recebido_em.utcoffset() is None:
        raise ErroAtestacaoFrete("instante confiável de verificação obrigatório")
    if (not isinstance(atestacao, Mapping)
            or atestacao.get("versao_atestacao") != 1
            or type(atestacao.get("versao_atestacao")) is not int
            or atestacao.get("emissor_id") != emissor_esperado):
        raise ErroAtestacaoFrete("emissor, contrato ou versão não confiável")
    sig = atestacao.get("assinatura_hmac_sha256")
    if not isinstance(sig, str) or not _SHA.fullmatch(sig):
        raise ErroAtestacaoFrete("assinatura HMAC-SHA256 ausente")
    assinado = dict(atestacao)
    del assinado["assinatura_hmac_sha256"]
    payload = serializacao_canonica(assinado)
    assinatura_esperada = hmac.new(
        chave_confiavel, b"NIVON_ATTESTATION_V1\x00" + dominio.encode() + b"\x00" + payload,
        sha256,
    ).hexdigest()
    if not hmac.compare_digest(sig, assinatura_esperada):
        raise ErroAtestacaoFrete("assinatura adulterada ou emissor desconhecido")
    emitido = _instante(atestacao.get("emitido_em"), "emitido_em")
    ate = _instante(atestacao.get("valido_ate"), "valido_ate")
    instante = recebido_em.astimezone(_UTC)
    if not (emitido <= instante <= ate and emitido < ate
            and ate-emitido <= timedelta(days=max_dias_validade)):
        raise ErroAtestacaoFrete("atestação expirada, futura ou com janela excessiva")
