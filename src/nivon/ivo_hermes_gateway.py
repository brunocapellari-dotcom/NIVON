"""Ponte de consulta IVO aos contratos Hermes: identidade, tenant e politica.

Sem verificador OIDC ou politica propria. Dependencias concretas devem vir
do backend Hermes. Falha fechado se autenticacao/OPA/OpenFGA indisponiveis.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime, timezone
from hashlib import sha256
from typing import Callable

from .ivo_conhecimento_adapter import ClaimCurado
from .ivo_pacote_evidencias import ContextoAcessoIVO, montar_pacote_evidencias


class AcessoNegadoIVO(PermissionError):
    """Mensagem generica para nao vazar token ou regras internas."""


@dataclass(frozen=True)
class EscopoHermesIVO:
    tenant: str
    projeto: str
    ator: str


@dataclass(frozen=True)
class VinculoRecursoIVO:
    """ACL/proveniencia obtida do registry do servidor, nunca do prompt."""
    claim_id: str
    fonte_id: str
    documento_sha256: str
    texto_sha256: str
    auditoria_id: str
    tenant: str
    projeto: str
    direito_consulta: bool
    verificado_em: datetime


def _instante(valor: datetime) -> datetime:
    if not isinstance(valor, datetime) or valor.tzinfo is None or valor.utcoffset() is None:
        raise AcessoNegadoIVO("acesso negado")
    return valor.astimezone(timezone.utc)


def _id(valor: object) -> bool:
    return isinstance(valor, str) and bool(re.fullmatch(r"[A-Za-z0-9_.:-]{1,128}", valor))


class GatewayHermesIVO:
    """Adaptador para Hermes IdentityVerifier, PolicyRequest e CompositePolicyEngine.

    Todos os resolvedores e o engine devem ser construidos pelo servidor.
    Nao e endpoint HTTP, nao aceita objetos PolicyDecision fornecidos pelo cliente.
    """

    def __init__(
        self, *, identity_verifier: object,
        scope_lookup: Callable[[str], EscopoHermesIVO],
        resource_lookup: Callable[[ClaimCurado], VinculoRecursoIVO],
        policy_request_factory: Callable[..., object],
        policy_engine: object, audience: str,
        issuers: frozenset[str], clock: Callable[[], datetime],
    ) -> None:
        if (
            not callable(getattr(identity_verifier, "verify", None))
            or not callable(scope_lookup) or not callable(resource_lookup)
            or not callable(policy_request_factory)
            or not callable(getattr(policy_engine, "authorize", None))
            or getattr(policy_engine, "external_required", None) is not True
            or getattr(policy_engine, "opa", None) is None
            or getattr(policy_engine, "openfga", None) is None
            or not isinstance(audience, str) or not audience.startswith("https://")
            or not isinstance(issuers, frozenset) or not issuers
            or any(not isinstance(x, str) or not x for x in issuers)
            or not callable(clock)
        ):
            raise AcessoNegadoIVO("acesso negado")
        self._verifier = identity_verifier
        self._scope = scope_lookup
        self._resource = resource_lookup
        self._request = policy_request_factory
        self._policy = policy_engine
        self._audience = audience
        self._issuers = issuers
        self._clock = clock

    def consultar(
        self, *, token: str, pergunta: str, claims: list[ClaimCurado],
        corte: datetime, limite: int = 5,
        planejador: Callable[[str], dict] | None = None,
    ) -> dict:
        """Token vem da camada de transporte autenticada; jamais da LLM."""
        if (
            not isinstance(token, str) or not 8 <= len(token) <= 8192
            or any(c.isspace() or ord(c) < 33 for c in token)
        ):
            raise AcessoNegadoIVO("acesso negado")
        try:
            identity = self._verifier.verify(token)
            subject = getattr(identity, "subject", None)
            issuer = getattr(identity, "issuer", None)
            audience = getattr(identity, "audience", None)
            if not _id(subject) or issuer not in self._issuers or audience != self._audience:
                raise ValueError("identidade invalida")
            scope = self._scope(subject)
            if (
                type(scope) is not EscopoHermesIVO or scope.ator != subject
                or scope.projeto != "NIVON" or not _id(scope.tenant)
            ):
                raise ValueError("escopo invalido")
            now = _instante(self._clock())
            asof = _instante(corte)
            if asof > now:
                raise ValueError("corte no futuro")
        except Exception:
            raise AcessoNegadoIVO("acesso negado") from None

        context = ContextoAcessoIVO(
            tenant=scope.tenant, projeto=scope.projeto, ator=subject, corte=asof,
        )

        def authorize(ctx: ContextoAcessoIVO, claim: ClaimCurado, action: str) -> bool:
            try:
                if ctx != context or action != "CONSULTAR_EVIDENCIA":
                    return False
                binding = self._resource(claim)
                if type(binding) is not VinculoRecursoIVO or binding.direito_consulta is not True:
                    return False
                if (
                    binding.tenant != scope.tenant or binding.projeto != "NIVON"
                    or binding.claim_id != claim.claim_id or binding.fonte_id != claim.fonte_id
                    or binding.documento_sha256 != claim.documento_sha256
                    or binding.auditoria_id != claim.auditoria_id
                    or binding.texto_sha256 != sha256(claim.texto.encode("utf-8")).hexdigest()
                    or _instante(binding.verificado_em) > asof
                ):
                    return False
                policy_request = self._request(
                    actor=subject, subject=subject, action="evidence:read",
                    resource=f"nivon:evidence:{scope.tenant}:{claim.documento_sha256}:{claim.claim_id}",
                    relation="can_read", risk="low", trust="untrusted",
                    external_write=False, money=False, production_admin=False,
                    requests_scope_increase=False,
                )
                decision = self._policy.authorize(policy_request)
                return (
                    getattr(decision, "allowed", None) is True
                    and getattr(decision, "requires_approval", None) is False
                )
            except Exception:
                return False

        result = montar_pacote_evidencias(
            pergunta=pergunta, contexto=context, claims=claims,
            autorizador=authorize, limite=limite, planejador=planejador,
        )
        result["fronteira_acesso"] = "HERMES_CONTRATO_SERVER_SIDE; E2E_REAL_PENDENTE"
        result["escrita_habilitada"] = False
        return result
