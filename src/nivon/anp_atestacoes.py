"""Atestações externas para vintages reais da ANP/LPC.

Protótipo offline: HMAC prova a integridade da declaração feita por um
emissor previamente confiável; NÃO prova por si só licença, publicação
oficial, verdade do XLSX, nem implementa a infraestrutura de custódia.
O módulo NÃO possui chave de emissão, chave default nem rotina de assinar.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from hashlib import sha256
import hmac
import json
import re
from typing import Mapping

DOMINIOS = frozenset({"DIREITOS_USO", "HOMOLOGACAO_LAYOUT"})
SHA = re.compile(r"^[0-9a-f]{64}$")
DOMAIN_PREFIX = b"NIVON_ANP_LPC_ATTESTATION_V1\x00"


class ErroAtestacaoANP(PermissionError):
    pass


def _timestamp(value: object, nome: str) -> datetime:
    if not isinstance(value, str):
        raise ErroAtestacaoANP(f"{nome}: instante com timezone obrigatório")
    try:
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ErroAtestacaoANP(f"{nome}: instante inválido") from exc
    if dt.tzinfo is None or dt.utcoffset() is None:
        raise ErroAtestacaoANP(f"{nome}: timezone obrigatório")
    return dt.astimezone(timezone.utc)


def _canon(payload: Mapping) -> bytes:
    try:
        return json.dumps(payload, sort_keys=True, ensure_ascii=True,
                          separators=(",", ":"), allow_nan=False).encode("utf-8")
    except (ValueError, TypeError, OverflowError) as exc:
        raise ErroAtestacaoANP("declaração não serializável") from exc


def validar_aprovacoes_anp(
    *, aprovacao: Mapping, confianca: Mapping,
    edicao_sha256: str, resumo_sha256: str,
    origem_url: str, publicacao_em: str,
    prova_publicacao_sha256: str, prova_direitos_sha256: str,
    indice_sha256: str, verificado_em: str,
    ids_revogados: frozenset[str] | None = None,
) -> dict[str, dict]:
    """Exige dois revisores, chaves independentes e vínculos imutáveis.

    A observação do instante de verificação é fornecida pelo controlador
    confiável, NÃO pelo documento de aprovação. O chamador deve garantir
    que chaves/configuração e lista de revogação não venham da origem.
    """
    if not isinstance(aprovacao, Mapping) or set(aprovacao) != DOMINIOS:
        raise ErroAtestacaoANP("dois domínios de atestação obrigatórios")
    if not isinstance(confianca, Mapping) or set(confianca) != DOMINIOS:
        raise ErroAtestacaoANP("registro externo de autoridades ausente")
    if (ids_revogados is None or not isinstance(ids_revogados, frozenset)
            or not all(isinstance(x, str) for x in ids_revogados)):
        raise ErroAtestacaoANP("lista confiável de revogação obrigatória")
    for v in (edicao_sha256, resumo_sha256, prova_publicacao_sha256,
              prova_direitos_sha256, indice_sha256):
        if not isinstance(v, str) or not SHA.fullmatch(v):
            raise ErroAtestacaoANP("SHA da evidência inválido")
    instante = _timestamp(verificado_em, "verificado_em")
    keys = []
    emissores = []
    for dom in sorted(DOMINIOS):
        trust = confianca[dom]
        if not isinstance(trust, Mapping) or set(trust) != {"chave", "emissor"}:
            raise ErroAtestacaoANP("registro de autoridade inválido")
        chave, emissor = trust["chave"], trust["emissor"]
        if (not isinstance(chave, bytes) or len(chave) < 32
                or not isinstance(emissor, str) or not emissor.strip()):
            raise ErroAtestacaoANP("chave/emissor não homologados")
        keys.append(chave)
        emissores.append(emissor)
    if keys[0] == keys[1] or emissores[0] == emissores[1]:
        raise ErroAtestacaoANP("segregação entre revisores obrigatória")

    esperado = {
        "versao": 1,
        "edicao_sha256": edicao_sha256,
        "resumo_sha256": resumo_sha256,
        "origem_url": origem_url,
        "publicado_em": _timestamp(publicacao_em, "publicado_em").isoformat(),
        "prova_publicacao_sha256": prova_publicacao_sha256,
        "prova_direitos_sha256": prova_direitos_sha256,
        "indice_sha256": indice_sha256,
        "operacao": "ARMAZENAMENTO_ANALITICO_NAO_COMERCIAL",
        "publicavel": False,
    }
    verificados = {}
    for dom in sorted(DOMINIOS):
        at = aprovacao[dom]
        if (not isinstance(at, Mapping) or set(at) !=
            set(esperado) | {
                "dominio", "emissor_id", "aprovacao_id", "emitido_em",
                "valido_ate", "assinatura_hmac_sha256",
            }):
            raise ErroAtestacaoANP("schema de atestação inválido")
        if (type(at.get("versao")) is not int or
            any(at.get(k) != v for k, v in esperado.items()) or
            at.get("dominio") != dom or
            at.get("emissor_id") != confianca[dom]["emissor"]):
            raise ErroAtestacaoANP("atestação não vinculada à edição ou ao escopo")
        aid = at.get("aprovacao_id")
        if (not isinstance(aid, str) or not 8 <= len(aid) <= 120
                or not re.fullmatch(r"[A-Za-z0-9_:.-]+", aid)
                or aid in ids_revogados):
            raise ErroAtestacaoANP("identificador de aprovação inválido ou revogado")
        assinatura = at["assinatura_hmac_sha256"]
        if not isinstance(assinatura, str) or not SHA.fullmatch(assinatura):
            raise ErroAtestacaoANP("assinatura HMAC não informada")
        unsigned = {k: v for k, v in at.items() if k != "assinatura_hmac_sha256"}
        assinatura_esperada = hmac.new(
            confianca[dom]["chave"], DOMAIN_PREFIX + dom.encode("ascii")
            + b"\x00" + _canon(unsigned), sha256,
        ).hexdigest()
        if not hmac.compare_digest(assinatura, assinatura_esperada):
            raise ErroAtestacaoANP("assinatura não autentica emissor ou documento")
        emitido = _timestamp(at["emitido_em"], "emitido_em")
        ate = _timestamp(at["valido_ate"], "valido_ate")
        if (not emitido <= instante <= ate or not emitido < ate or
                ate-emitido > timedelta(days=7)):
            raise ErroAtestacaoANP("atestação expirada, futura ou excessiva")
        verificados[dom] = {
            "aprovacao_id": aid, "emissor_id": at["emissor_id"],
            "assinatura_sha256": sha256(assinatura.encode()).hexdigest(),
            "emitido_em": emitido.isoformat(), "valido_ate": ate.isoformat(),
        }
    if verificados["DIREITOS_USO"]["aprovacao_id"] == verificados["HOMOLOGACAO_LAYOUT"]["aprovacao_id"]:
        raise ErroAtestacaoANP("identificadores de aprovação não segregados")
    return verificados
