"""Limites máximos de frescor do briefing NIVON, derivados da auditoria PR #13.

Estes limites são *backstops*: dado dentro da janela ainda depende de
calendário de pregão, licenças, vintage e homologação independente.
Não aplicável à janela móvel de 24h das notícias.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

LIMITES_FRESCURA = {
    "BOLSAS": timedelta(hours=96),
    "CAMBIO": timedelta(hours=96),
    "PRECOS": timedelta(days=7),
    "SAFRA": timedelta(days=45),
    "PORTOS": timedelta(hours=48),
    "DIESEL": timedelta(days=16),
    "FERTILIZANTES": timedelta(days=45),
    "CLIMA": timedelta(hours=48),
    "LOGISTICA": timedelta(hours=72),
    "GEOPOLITICA": timedelta(hours=72),
}

GRUPOS_PARA_SECAO = {
    "CHICAGO": "BOLSAS",
    "ICE": "BOLSAS",
    "CAMBIO": "CAMBIO",
    "MERCADO_FISICO": "PRECOS",
    "PECUARIA": "PRECOS",
    "ENERGIA": "PRECOS",
}


def _timestamp(valor: str, campo: str) -> datetime:
    if not isinstance(valor, str) or "T" not in valor:
        raise ValueError(f"{campo} exige timestamp ISO com fuso")
    try:
        d = datetime.fromisoformat(valor.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError(f"{campo} exige timestamp ISO válido") from exc
    if d.tzinfo is None or d.utcoffset() is None:
        raise ValueError(f"{campo} sem fuso")
    return d.astimezone(timezone.utc)


def validar_frescor_indicador(*, secao: str, referencia: str, gerado_em: str) -> None:
    """Falha fechada se um indicador é velho ou ainda não ocorreu."""
    if secao not in LIMITES_FRESCURA:
        raise ValueError("seção desconhecida para frescor")
    agora = _timestamp(gerado_em, "geração")
    ref = _timestamp(referencia, "referência")
    if ref > agora:
        raise ValueError("referência futura")
    if agora - ref > LIMITES_FRESCURA[secao]:
        raise ValueError("indicador vencido: referência fora da janela da seção")


def secao_do_grupo(*, grupo: str, secao_declarada: str | None = None) -> str:
    """A seção original vence o fallback; DIESEL não vira preço spot."""
    if secao_declarada is not None:
        if secao_declarada not in LIMITES_FRESCURA:
            raise ValueError("seção declarada incompatível com contrato")
        if grupo == "ENERGIA" and secao_declarada not in ("DIESEL", "PRECOS"):
            raise ValueError("seção de energia incoerente")
        if grupo in ("CHICAGO", "ICE") and secao_declarada != "BOLSAS":
            raise ValueError("seção de bolsa incoerente")
        if grupo == "CAMBIO" and secao_declarada != "CAMBIO":
            raise ValueError("seção de câmbio incoerente")
        if grupo in ("MERCADO_FISICO", "PECUARIA") and secao_declarada != "PRECOS":
            raise ValueError("seção de mercado físico incoerente")
        return secao_declarada
    if grupo not in GRUPOS_PARA_SECAO:
        raise ValueError("grupo sem política de frescor")
    return GRUPOS_PARA_SECAO[grupo]
