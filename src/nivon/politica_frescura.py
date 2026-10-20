"""Política temporal explícita de briefing; não transforma série antiga em atual."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

LIMITES_HORAS = {"BOLSAS": 168, "CAMBIO": 168}


class ErroFrescura(ValueError):
    pass


def aplicar_politica_frescura(indicadores: list[dict], *,
                            gerado_em: str,
                            limites: dict[str, int] | None = None) -> dict:
    """Remove referências velhas/futuras nas seções críticas antes da edição.

    Sete dias por padrão evita bloquear feriados prolongados; não representa
    SLA contratado. Adaptação por mercado exige auditoria e documentação.
    """
    thresholds = LIMITES_HORAS if limites is None else limites
    try:
        gerado = datetime.fromisoformat(gerado_em.replace("Z","+00:00"))
    except (TypeError,ValueError) as exc:
        raise ErroFrescura("gerado_em inválido") from exc
    if gerado.tzinfo is None:
        raise ErroFrescura("gerado_em sem fuso")
    if not isinstance(indicadores,list) or not isinstance(thresholds,dict):
        raise ErroFrescura("entrada/limites inválidos")
    for k,v in thresholds.items():
        if k not in LIMITES_HORAS or type(v) is not int or not 1<=v<=336:
            raise ErroFrescura("limite temporal fora do contrato")
    aceitos=[]
    recusados=[]
    for i,item in enumerate(indicadores):
        if not isinstance(item,dict):
            recusados.append({"indice":i,"motivo":"INDICADOR_MALFORMADO"})
            continue
        secao=item.get("secao")
        if secao not in thresholds:
            aceitos.append(item)
            continue
        try:
            dt=datetime.fromisoformat(item["referencia"].replace("Z","+00:00"))
            if dt.tzinfo is None:
                raise ValueError("timezone ausente")
        except (ValueError,TypeError,AttributeError,KeyError):
            recusados.append({"indice":i,"secao":secao,"motivo":"REFERENCIA_INVALIDA"})
            continue
        delta=gerado.astimezone(timezone.utc)-dt.astimezone(timezone.utc)
        if delta<timedelta(0):
            recusados.append({"indice":i,"secao":secao,"motivo":"REFERENCIA_FUTURA"})
        elif delta>timedelta(hours=thresholds[secao]):
            recusados.append({"indice":i,"secao":secao,"motivo":"REFERENCIA_VENCIDA"})
        else:
            aceitos.append(item)
    return {"indicadores":aceitos,"recusados":recusados,"limites_horas":dict(thresholds)}
