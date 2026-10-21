"""Calendário explícito de sessões para análise descritiva OFFLINE do NIVON.

O calendário é recebido, não baixado; SHA e fonte são declarações do produtor.
Confirma cobertura das datas declaradas e rejeita lacunas, mas NÃO verifica se
a fonte publicou as sessões ou se os dias são pregões oficiais de fato.
"""
from __future__ import annotations

from datetime import date, datetime, timezone
from typing import Mapping, Sequence


class ErroCalendarioMercado(ValueError):
    """Calendário de sessões ausente, incoerente ou temporalmente inválido."""


def _instante(v: object, campo: str) -> datetime:
    if not isinstance(v, str) or len(v) > 45:
        raise ErroCalendarioMercado(f"{campo}: instante obrigatório")
    try:
        t = datetime.fromisoformat(v)
    except ValueError as exc:
        raise ErroCalendarioMercado(f"{campo}: instante inválido") from exc
    if t.tzinfo is None or t.utcoffset() is None:
        raise ErroCalendarioMercado(f"{campo}: fuso explícito obrigatório")
    return t.astimezone(timezone.utc)


def _dia(v: object) -> date:
    if not isinstance(v, str) or len(v) != 10:
        raise ErroCalendarioMercado("data de sessão AAAA-MM-DD obrigatória")
    try:
        d = date.fromisoformat(v)
    except ValueError as exc:
        raise ErroCalendarioMercado("data de sessão inválida") from exc
    if d.isoformat() != v:
        raise ErroCalendarioMercado("data de sessão não canônica")
    return d


def validar_cobertura_calendario(
    calendario: Mapping, *, mercado: str, periodos: Sequence[str], as_of: str,
) -> dict:
    """Confirma que todos os pregões declarados entre duas datas têm cotação.

    Uma edição de calendário capturada somente depois do corte é recusada.
    Para replays passados, fornecer o vintage que existia naquele corte.
    """
    corte = _instante(as_of, "as_of")
    if not isinstance(calendario, Mapping):
        raise ErroCalendarioMercado("calendário ausente")
    if calendario.get("mercado") != mercado or mercado not in ("CME", "ICE", "FISICO"):
        raise ErroCalendarioMercado("calendário de mercado diferente")
    fonte = calendario.get("fonte_id")
    digest = calendario.get("edicao_sha256")
    if not isinstance(fonte, str) or not 1 <= len(fonte) <= 120 or fonte.strip() != fonte:
        raise ErroCalendarioMercado("fonte de calendário ausente")
    if (not isinstance(digest, str) or len(digest) != 64 or
            any(c not in "0123456789abcdef" for c in digest)):
        raise ErroCalendarioMercado("SHA da edição de calendário inválido")
    publicado = _instante(calendario.get("publicacao_em"), "publicacao_em")
    coletado = _instante(calendario.get("coleta_em"), "coleta_em")
    if not publicado <= coletado <= corte:
        raise ErroCalendarioMercado("calendário publicado ou coletado depois do corte")
    sessoes = calendario.get("sessoes")
    if not isinstance(sessoes, (list, tuple)) or not 1 <= len(sessoes) <= 5000:
        raise ErroCalendarioMercado("lista de sessões inválida")
    dias = [_dia(d) for d in sessoes]
    if any(a >= b for a, b in zip(dias, dias[1:])):
        raise ErroCalendarioMercado("sessões repetidas ou fora de ordem")
    if not isinstance(periodos, (list, tuple)) or not periodos:
        raise ErroCalendarioMercado("série sem datas")
    observados = [_dia(d) for d in periodos]
    if any(a >= b for a, b in zip(observados, observados[1:])):
        raise ErroCalendarioMercado("preços repetidos ou fora de ordem")
    if observados[0] < dias[0] or observados[-1] > dias[-1]:
        raise ErroCalendarioMercado("calendário não cobre todas as observações")
    esperados = [d for d in dias if observados[0] <= d <= observados[-1]]
    if esperados != observados:
        raise ErroCalendarioMercado("lacuna de sessão declarada no calendário")
    return {
        "status": "COBERTURA_DECLARADA_NAO_HOMOLOGADA",
        "mercado": mercado,
        "fonte_id": fonte,
        "edicao_sha256": digest,
        "publicacao_em": publicado.isoformat(),
        "coleta_em": coletado.isoformat(),
        "sessoes_conferidas": len(observados),
        "publicavel": False,
        "calendario_oficial_comprovado": False,
    }


def indexar_calendario_sessoes(
    calendario: Mapping, *, mercado: str, as_of: str,
) -> tuple[dict[str, int], dict]:
    """Indexa uma única vez uma edição declarada para validar horizontes.

    O calendário precisa ter captura anterior ao corte analisado. A validade
    oficial das datas permanece uma verificação externa obrigatória.
    """
    if not isinstance(calendario, Mapping):
        raise ErroCalendarioMercado("calendário ausente")
    sessoes = calendario.get("sessoes")
    prova = validar_cobertura_calendario(
        calendario, mercado=mercado, periodos=sessoes, as_of=as_of,
    )
    return {dia: i for i, dia in enumerate(sessoes)}, prova
