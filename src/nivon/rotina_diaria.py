"""Preparação agendável do briefing completo — sem coleta ou envio implícito.

Dados entram por contratos homologados. Falta de CBOT/câmbio não vira cotação
inventada; impede preparação para entrega quando segmento é obrigatório.
"""
from __future__ import annotations

from datetime import datetime
from hashlib import sha256
from typing import Callable
from zoneinfo import ZoneInfo

from .briefing_composto import montar_briefing
from .politica_frescura import aplicar_politica_frescura
from .outbox_briefing import agendar_briefing


class ErroRotina(ValueError):
    pass


FUSO = ZoneInfo("America/Sao_Paulo")
ALLOWED_SECTIONS = frozenset({
    "BOLSAS","CAMBIO","PRECOS","SAFRA","PORTOS","DIESEL",
    "FERTILIZANTES","CLIMA","LOGISTICA","GEOPOLITICA","FRETES",
})


def preparar_rotina(*, pacote: dict, gerado_em: str,
                   obrigatorias: frozenset[str] = frozenset({"BOLSAS","CAMBIO"}),
                   auditor: Callable | None = None,
                   db=None, destinatario_hmac: str | None = None,
                   agendar: bool = False) -> dict:
    """Gera e audita o briefing. Sem envio nem alteração em fonte externa.

    agendar=False: dry-run seguro; agendar=True requer banco persistente,
    destinatário pseudonimizado e auditor explícito positivo.
    """
    if not isinstance(pacote,dict):
        raise ErroRotina("pacote precisa ser objeto JSON")
    if not isinstance(obrigatorias,frozenset) or not obrigatorias <= ALLOWED_SECTIONS:
        raise ErroRotina("seções obrigatórias inválidas")
    try:
        now=datetime.fromisoformat(gerado_em.replace("Z","+00:00"))
    except (TypeError,ValueError) as exc:
        raise ErroRotina("geração sem instante válido") from exc
    if now.tzinfo is None:
        raise ErroRotina("geração sem timezone")
    frescura=aplicar_politica_frescura(
        pacote.get("indicadores",[]),gerado_em=gerado_em)
    payload=montar_briefing(
        noticias=pacote.get("noticias",[]),fontes=pacote.get("fontes",{}),
        data=gerado_em,indicadores=frescura["indicadores"],
        fretes=pacote.get("fretes",[]))
    payload["rejeicoes"].extend([
        {"tipo":"FRESCURA","motivo":r["motivo"],"secao":r.get("secao")}
        for r in frescura["recusados"]
    ])
    faltam=sorted(obrigatorias-set(payload["secoes_presentes"]))
    if faltam:
        return {
            "status":"BLOQUEADO_INDICADORES_ESSENCIAIS",
            "faltam":faltam,"hash":payload["sha256"],
            "rejeicoes":payload["rejeicoes"],
            "agendado":False,
        }
    if auditor is None:
        return {
            "status":"AGUARDA_AUDITOR",
            "hash":payload["sha256"],
            "rejeicoes":payload["rejeicoes"],
            "agendado":False,
        }
    if auditor(payload) is not True:
        return {"status":"REPROVADO_AUDITORIA",
                "hash":payload["sha256"],"agendado":False}
    if agendar:
        # Uma aprovação humana/IA não substitui integridade numérica,
        # direitos ou frescor. Descarta a edição para envio se qualquer dado
        # de mercado ou frete necessário tiver sido rejeitado.
        criticas=[x for x in payload["rejeicoes"]
                  if x.get("tipo") in {"INDICADOR","FRETE","FRESCURA"}]
        if criticas:
            return {"status":"BLOQUEADO_PRE_PUBLICACAO",
                    "hash":payload["sha256"],"agendado":False,
                    "rejeicoes_criticas":criticas,
                    "rejeicoes":payload["rejeicoes"]}
    if not agendar:
        return {"status":"VALIDADO_DRY_RUN",
                "hash":payload["sha256"],"agendado":False,
                "previsao_envio":False,"texto":payload["texto"]}
    if db is None or not destinatario_hmac:
        raise ErroRotina("outbox persistente e identificador HMAC são necessários")
    dia=now.astimezone(FUSO).date().isoformat()
    agendamento=agendar_briefing(
        db,dia_local=dia,destinatario_hmac=destinatario_hmac,
        briefing=payload,agora=gerado_em,auditoria_aprovada=True)
    return {
        "status":"AGENDADO_NA_OUTBOX_SEM_ENVIO",
        "hash":payload["sha256"],"agendado":True,
        "outbox":agendamento,"dia_local":dia,
        "rejeicoes":payload["rejeicoes"],
    }
