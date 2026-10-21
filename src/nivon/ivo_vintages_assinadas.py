"""IVO: replay as-of de decisoes Knowledge Factory com integridade autenticada.

HMAC-SHA256 v1 (chave externa ao repositorio), hash-chain de eventos e
ancora temporal independente obrigatoria. Nao cria nem guarda chaves,
nao assina eventos nem altera Segundo Cerebro. Chaves e ancoras de verdade
dependem da infraestrutura do Hermes/Knowledge Factory.
"""
from __future__ import annotations

import hmac
import json
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from hashlib import sha256
from typing import Callable

from .ivo_second_brain_bridge import AtestacaoCanonicaIVO, ErroProvenienciaIVO

DOMAIN = b"NIVON-IVO-VINTAGE-HMAC-SHA256-V1\x00"
GENESIS = "0" * 64
IDENT = re.compile(r"[a-zA-Z0-9_.:-]{1,128}\Z")
HASH = re.compile(r"[a-f0-9]{64}\Z")
FIELDS = frozenset({
    "seq", "prev_sha256", "evento", "tenant", "consumidor", "operacao",
    "claim_id", "evidence_id", "source_id", "registro_sha256",
    "evidencia_sha256", "fonte_url", "decision_id", "auditoria_id",
    "publicado_em", "coletado_em", "aprovado_em", "gravado_em",
    "efetivo_em", "direito_consulta",
})


def _date(value: object) -> datetime:
    if isinstance(value, str):
        try:
            value = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            pass
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise ErroProvenienciaIVO("evento sem timestamp com fuso")
    return value.astimezone(timezone.utc)


def _identifier(value: object) -> str:
    if not isinstance(value, str) or not IDENT.fullmatch(value):
        raise ErroProvenienciaIVO("identificador de evento invalido")
    return value


def _digest(value: object) -> str:
    if not isinstance(value, str) or not HASH.fullmatch(value):
        raise ErroProvenienciaIVO("hash de evento invalido")
    return value


def _json(value: object) -> bytes:
    try:
        raw = json.dumps(value, sort_keys=True, separators=(",", ":"),
                         ensure_ascii=False, allow_nan=False).encode("utf-8")
    except (ValueError, TypeError, UnicodeError) as exc:
        raise ErroProvenienciaIVO("evento nao serializavel") from exc
    if len(raw) > 16_384:
        raise ErroProvenienciaIVO("evento excessivo")
    return raw


@dataclass(frozen=True)
class EnvelopeAssinadoIVO:
    chave_id: str
    payload: dict
    mac_sha256: str


@dataclass(frozen=True)
class _EventoVerificado:
    payload: dict
    ancorado_em: datetime
    digest: str


class RegistroVintagesIVO:
    """Valida cadeia completa e apenas usa eventos conhecidos no instante as-of.

    resolver_chave(kid): bytes >= 32 (KMS/segredos fora do codigo).
    obter_ancora(digest): timestamp CONFIRMADO POR FONTE EXTERNA, nao dado
    declarado no envelope. Sem ancora, negar; HMAC sozinho nao prova horario.
    """

    def __init__(
        self, eventos: list[EnvelopeAssinadoIVO], *,
        resolver_chave: Callable[[str], bytes],
        obter_ancora: Callable[[str], datetime],
    ) -> None:
        if (not isinstance(eventos, list) or len(eventos) > 1000
                or not callable(resolver_chave) or not callable(obter_ancora)):
            raise ErroProvenienciaIVO("registro e verificadores obrigatorios")
        self._sealed = []
        for event in eventos:
            if type(event) is not EnvelopeAssinadoIVO:
                raise ErroProvenienciaIVO("envelope invalido")
            kid = _identifier(event.chave_id)
            signature = _digest(event.mac_sha256)
            raw = _json(event.payload)
            self._sealed.append((kid, signature, raw))
        self._sealed = tuple(self._sealed)
        self._keys = resolver_chave
        self._anchors = obter_ancora

    def _read_events(self) -> list[_EventoVerificado]:
        prev = GENESIS
        prev_recorded = None
        prev_anchor = None
        decisions = set()
        result = []
        for index, (kid, signature, raw) in enumerate(self._sealed, 1):
            try:
                key = self._keys(kid)
                if not isinstance(key, bytes) or len(key) < 32:
                    raise ErroProvenienciaIVO("chave insuficiente")
                expected = hmac.new(key, DOMAIN + raw, sha256).hexdigest()
                if not hmac.compare_digest(signature, expected):
                    raise ErroProvenienciaIVO("assinatura HMAC divergente")
                p = json.loads(raw)
                if not isinstance(p, dict) or frozenset(p) != FIELDS:
                    raise ErroProvenienciaIVO("schema do evento divergente")
                if type(p["seq"]) is not int or p["seq"] != index:
                    raise ErroProvenienciaIVO("lacuna ou duplicacao de sequencia")
                if _digest(p["prev_sha256"]) != prev:
                    raise ErroProvenienciaIVO("cadeia alterada")
                for field in (
                    "tenant", "consumidor", "operacao", "claim_id",
                    "evidence_id", "source_id", "decision_id", "auditoria_id",
                ):
                    _identifier(p[field])
                for field in ("registro_sha256", "evidencia_sha256"):
                    _digest(p[field])
                if (not isinstance(p["fonte_url"], str)
                        or not p["fonte_url"].startswith("https://")
                        or len(p["fonte_url"]) > 2048):
                    raise ErroProvenienciaIVO("fonte invalida")
                if p["evento"] not in ("PROMOVIDO", "REVOGADO"):
                    raise ErroProvenienciaIVO("tipo de evento invalido")
                if type(p["direito_consulta"]) is not bool:
                    raise ErroProvenienciaIVO("direito malformado")
                if p["direito_consulta"] is not (p["evento"] == "PROMOVIDO"):
                    raise ErroProvenienciaIVO("semantica da decisao contraditoria")
                publication = _date(p["publicado_em"])
                collection = _date(p["coletado_em"])
                approved = _date(p["aprovado_em"])
                effective = _date(p["efetivo_em"])
                recorded = _date(p["gravado_em"])
                if not publication <= collection <= approved <= recorded:
                    raise ErroProvenienciaIVO("ordem temporal impossivel")
                if not approved <= effective <= recorded:
                    raise ErroProvenienciaIVO("efeito futuro ou retroativo nao auditado")
                if prev_recorded is not None and recorded < prev_recorded:
                    raise ErroProvenienciaIVO("cadeia cronologica invertida")
                event_digest = sha256(_json({
                    "kid": kid, "mac_sha256": signature, "payload": p,
                })).hexdigest()
                anchor = _date(self._anchors(event_digest))
                if anchor < recorded or (prev_anchor and anchor < prev_anchor):
                    raise ErroProvenienciaIVO("ancora cronologicamente impossivel")
                decision_key = (p["tenant"], p["decision_id"])
                if decision_key in decisions:
                    raise ErroProvenienciaIVO("decision_id duplicado")
                decisions.add(decision_key)
            except ErroProvenienciaIVO:
                raise
            except Exception:
                raise ErroProvenienciaIVO("verificacao de evento indisponivel") from None
            result.append(_EventoVerificado(p, anchor, event_digest))
            prev, prev_recorded, prev_anchor = event_digest, recorded, anchor
        return result

    def autorizador(
        self, *, tenant: str, consumidor: str = "NIVON",
        operacao: str = "CONSULTAR_EVIDENCIA",
    ) -> Callable[[str, str, str, datetime], AtestacaoCanonicaIVO]:
        _identifier(tenant)
        _identifier(consumidor)
        _identifier(operacao)

        def verificar(
            claim_id: str, registro_sha256: str,
            evidencia_sha256: str, corte: datetime,
        ) -> AtestacaoCanonicaIVO:
            _identifier(claim_id)
            _digest(registro_sha256)
            _digest(evidencia_sha256)
            asof = _date(corte)
            # Checar a cadeia integral; nao confiar em prefixo parcialmente
            # adulterado, nem retornar dados antes de validar ancoras.
            events = self._read_events()
            latest = None
            for item in events:
                p = item.payload
                if (p["tenant"] != tenant or p["consumidor"] != consumidor
                        or p["operacao"] != operacao or p["claim_id"] != claim_id):
                    continue
                if item.ancorado_em > asof:
                    continue
                if _date(p["efetivo_em"]) > asof:
                    continue
                latest = item
            if latest is None or latest.payload["evento"] != "PROMOVIDO":
                raise ErroProvenienciaIVO("sem decisao canonica vigente no corte")
            p = latest.payload
            if (p["registro_sha256"] != registro_sha256
                    or p["evidencia_sha256"] != evidencia_sha256):
                raise ErroProvenienciaIVO("vintage substituida ou hashes diferentes")
            return AtestacaoCanonicaIVO(
                claim_id=claim_id, evidence_id=p["evidence_id"],
                source_id=p["source_id"], tenant=tenant, consumidor=consumidor,
                registro_sha256=p["registro_sha256"],
                evidencia_sha256=p["evidencia_sha256"],
                fonte_url=p["fonte_url"], decision_id=p["decision_id"],
                auditoria_id=p["auditoria_id"],
                aprovado_em=_date(p["aprovado_em"]),
                verificado_em=latest.ancorado_em,
                promocao_confirmada=True, direito_consultar=True,
                vigente_no_corte=True,
            )
        return verificar
