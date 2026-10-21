"""Verificação local de integridade de snapshot IVO com chave de confiança externa.

Não assina documentos, não armazena a chave e não certifica licença ou revisão
humana. A chave deve ser fornecida por canal de confiança FORA do snapshot.
A autenticação criptográfica NÃO equivale à aprovação canônica da Knowledge
Factory/Segundo Cérebro. Não executa LLM, ferramentas, rede ou escrita.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import re
from dataclasses import asdict
from datetime import datetime, timezone

from .ivo_conhecimento_adapter import (
    ClaimCurado, ErroConhecimento, _data, recuperar_claims_asof,
)

_AUDIENCIA = "NIVON_IVO_KNOWLEDGE_READ_V1"
_CAMPOS = frozenset({
    "versao", "audiencia", "emissor_id", "contexto_id",
    "emitido_em", "expira_em", "snapshot_sha256", "assinatura_hmac_sha256",
})
_ID = re.compile(r"[A-Z][A-Z0-9_]{2,70}\Z")
_SHA = re.compile(r"[a-f0-9]{64}\Z")


def _digest_snapshot(claims: list[ClaimCurado]) -> str:
    """Inclui TODOS os campos de cada claim, não só seu texto/hash de origem."""
    if not isinstance(claims, list) or not 0 < len(claims) <= 5000:
        raise ErroConhecimento("snapshot ausente ou excessivo")
    ids = set()
    registros = []
    for claim in claims:
        if not isinstance(claim, ClaimCurado):
            raise ErroConhecimento("claim não é registro estruturado")
        claim.validar()
        if claim.claim_id in ids:
            raise ErroConhecimento("claim_id duplicado no snapshot")
        ids.add(claim.claim_id)
        obj = asdict(claim)
        for k in ("referencia_em", "publicado_em", "coletado_em", "validado_em",
                  "suplantado_em"):
            if obj[k] is not None:
                obj[k] = _data(obj[k], k).isoformat()
        registros.append(obj)
    registros.sort(key=lambda r: r["claim_id"])
    payload = json.dumps(
        registros, sort_keys=True, ensure_ascii=False, allow_nan=False,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _mac_payload(manifesto: dict) -> bytes:
    dados = {k: v for k, v in manifesto.items() if k != "assinatura_hmac_sha256"}
    return (b"NIVON:IVO:SNAPSHOT:V1\n" +
            json.dumps(dados, sort_keys=True, ensure_ascii=False,
                       allow_nan=False, separators=(",", ":")).encode("utf-8"))


def verificar_snapshot_assinado(
    claims: list[ClaimCurado], *, manifesto: dict,
    chave_confiavel: bytes, emissor_confiavel: str, contexto_esperado: str,
    corte: datetime, verificado_em: datetime | None = None,
) -> dict:
    """Somente evidência de integridade/autoria da chave pré-configurada.

    O operador deve obter chave e identificação esperada de um cofre confiável,
    não de campos do documento/XML/prompt. Exige assinatura do snapshot inteiro
    e da janela de validade, rejeitando assinatura de outro contexto.
    """
    if not isinstance(manifesto, dict) or set(manifesto) != _CAMPOS:
        raise ErroConhecimento("manifesto assinado com esquema inesperado")
    if not isinstance(chave_confiavel, bytes) or len(chave_confiavel) < 32:
        raise ErroConhecimento("chave confiável insuficiente")
    if not isinstance(emissor_confiavel, str) or not _ID.fullmatch(emissor_confiavel):
        raise ErroConhecimento("emissor confiável não configurado")
    if not isinstance(contexto_esperado, str) or not _ID.fullmatch(contexto_esperado):
        raise ErroConhecimento("contexto confiável não configurado")
    for nome in ("emissor_id", "contexto_id"):
        valor = manifesto[nome]
        if not isinstance(valor, str) or not _ID.fullmatch(valor):
            raise ErroConhecimento(f"{nome}: identificador inválido")
    if (manifesto["versao"] != "1.0.0"
            or manifesto["audiencia"] != _AUDIENCIA
            or manifesto["emissor_id"] != emissor_confiavel
            or manifesto["contexto_id"] != contexto_esperado):
        raise ErroConhecimento("emissor, contexto ou audiência divergentes")
    for nome in ("snapshot_sha256", "assinatura_hmac_sha256"):
        if (not isinstance(manifesto[nome], str)
                or not _SHA.fullmatch(manifesto[nome])):
            raise ErroConhecimento(f"{nome} inválido")
    emitido = _data(manifesto["emitido_em"], "emitido_em")
    expira = _data(manifesto["expira_em"], "expira_em")
    corte = _data(corte, "corte")
    agora = _data(verificado_em or datetime.now(timezone.utc), "verificado_em")
    if not emitido <= corte <= agora < expira:
        raise ErroConhecimento("atestado fora da competência/validade temporal")
    digest = _digest_snapshot(claims)
    if not hmac.compare_digest(digest, manifesto["snapshot_sha256"]):
        raise ErroConhecimento("snapshot alterado ou não correspondente")
    mac = hmac.new(chave_confiavel, _mac_payload(manifesto),
                   hashlib.sha256).hexdigest()
    if not hmac.compare_digest(mac, manifesto["assinatura_hmac_sha256"]):
        raise ErroConhecimento("assinatura de origem inválida")
    return {
        "snapshot_sha256": digest,
        "emissor_id": emissor_confiavel,
        "contexto_id": contexto_esperado,
        "atestado_emitido_em": emitido.isoformat(),
        "atestado_expira_em": expira.isoformat(),
        "assinatura_hmac_verificada": True,
        "aprovacao_externa_verificada": False,
        "publicacao_autorizada": False,
        "escrita_canonica_autorizada": False,
        "nota": "Autenticidade da chave local não homologa direitos, auditoria nem uso público.",
    }


def recuperar_claims_de_snapshot_assinado(
    claims: list[ClaimCurado], *, manifesto: dict,
    chave_confiavel: bytes, emissor_confiavel: str, contexto_esperado: str,
    pergunta: str, corte: datetime, limite: int = 5,
    dominio: str | None = None,
    verificado_em: datetime | None = None,
) -> dict:
    """Verifica atestado ANTES de interpretar claims de snapshot não confiável."""
    auditoria = verificar_snapshot_assinado(
        claims, manifesto=manifesto, chave_confiavel=chave_confiavel,
        emissor_confiavel=emissor_confiavel, contexto_esperado=contexto_esperado,
        corte=corte, verificado_em=verificado_em,
    )
    r = recuperar_claims_asof(
        claims, pergunta=pergunta, corte=corte, limite=limite, dominio=dominio,
    )
    r["atestado_de_integridade"] = auditoria
    r["aprovacao_externa_verificada"] = False
    r["publicacao_autorizada"] = False
    return r
