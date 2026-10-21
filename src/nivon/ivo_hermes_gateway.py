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

    def _autenticar(self, *, token: str, corte: datetime) -> tuple[ContextoAcessoIVO, datetime]:
        """Identidade e tenant SOMENTE via componentes autenticados do servidor."""
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
            context = ContextoAcessoIVO(
                tenant=scope.tenant, projeto=scope.projeto, ator=subject, corte=asof,
            )
            return context, now
        except Exception:
            raise AcessoNegadoIVO("acesso negado") from None

    def _consultar_autorizado(
        self, *, pergunta: str, claims: list[ClaimCurado],
        context: ContextoAcessoIVO, agora: datetime,
        limite: int, planejador: Callable[[str], dict] | None,
    ) -> dict:
        """O corte controla dados historicos; ACL atual usa o instante atual."""
        def authorize(ctx: ContextoAcessoIVO, claim: ClaimCurado, action: str) -> bool:
            try:
                if ctx != context or action != "CONSULTAR_EVIDENCIA":
                    return False
                binding = self._resource(claim)
                if type(binding) is not VinculoRecursoIVO or binding.direito_consulta is not True:
                    return False
                if (
                    binding.tenant != context.tenant or binding.projeto != "NIVON"
                    or binding.claim_id != claim.claim_id or binding.fonte_id != claim.fonte_id
                    or binding.documento_sha256 != claim.documento_sha256
                    or binding.auditoria_id != claim.auditoria_id
                    or binding.texto_sha256 != sha256(claim.texto.encode("utf-8")).hexdigest()
                    or _instante(binding.verificado_em) > agora
                ):
                    return False
                policy_request = self._request(
                    actor=context.ator, subject=context.ator, action="evidence:read",
                    resource=f"nivon:evidence:{context.tenant}:{claim.documento_sha256}:{claim.claim_id}",
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

    def consultar(
        self, *, token: str, pergunta: str, claims: list[ClaimCurado],
        corte: datetime, limite: int = 5,
        planejador: Callable[[str], dict] | None = None,
    ) -> dict:
        """Consulta de claims cuja origem ja foi auditada por backend confiavel."""
        context, agora = self._autenticar(token=token, corte=corte)
        return self._consultar_autorizado(
            pergunta=pergunta, claims=claims, context=context,
            agora=agora, limite=limite, planejador=planejador,
        )

    def consultar_canonicas(
        self, *, token: str, pergunta: str, exportacoes: list,
        historico: object, corte: datetime, limite: int = 5,
        planejador: Callable[[str], dict] | None = None,
    ) -> dict:
        """Acesso em duas dimensoes: vintage historica + direito vigente hoje.

        Exige RegistroVintagesIVO injetado no servidor com key/anchor/head
        independentes e ExportacaoSegundoCerebro autorizada. Nao expor como
        endpoint nem aceitar componentes arbitrarios do usuario ou do LLM.
        """
        from .ivo_second_brain_bridge import normalizar_exportacoes_canonicas
        from .ivo_vintages_assinadas import RegistroVintagesIVO

        context, agora = self._autenticar(token=token, corte=corte)
        if type(historico) is not RegistroVintagesIVO:
            raise AcessoNegadoIVO("acesso negado")
        try:
            normalized = normalizar_exportacoes_canonicas(
                exportacoes=exportacoes, tenant=context.tenant,
                corte=context.corte,
                verificador=historico.autorizador(
                    tenant=context.tenant, consumidor="NIVON",
                    operacao="CONSULTAR_EVIDENCIA",
                ),
            )
        except Exception:
            # Nao divulgar se havia informacao, rights, chaves ou datas.
            raise AcessoNegadoIVO("acesso negado") from None
        response = self._consultar_autorizado(
            pergunta=pergunta, claims=normalized["claims"], context=context,
            agora=agora, limite=limite, planejador=planejador,
        )
        visible = {e["claim_id"] for e in response["evidencias"]}
        response["proveniencia_canonica"] = [
            {
                "claim_id": m["claim_id"], "evidence_id": m["evidence_id"],
                "decision_id": m["decision_id"],
                "registro_sha256": m["registro_sha256"],
                "evidencia_sha256": m["evidencia_sha256"],
                "referencia_granularidade": m["referencia_granularidade"],
            }
            for m in normalized["metadados"] if m["claim_id"] in visible
        ]
        response["duplo_gate"] = (
            "REPLAY_HISTORICO_ASOF_E_ACL_ATUAL_EM_CONTRATOS_OFFLINE;"
            "INFRAESTRUTURA_EXTERNA_NAO_HOMOLOGADA"
        )
        return response
