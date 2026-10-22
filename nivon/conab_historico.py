"""CONAB — contrato estrito para série histórica de safra, independente de levantamentos.

Não atribui datas de publicação a linhas históricas; distingue valor ausente de zero.
Não coleta ou grava por conta própria. Fonte única: CONAB (agrobr 2.0.0).
"""
from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
import re

FONTE="conab_serie_historica"
URL="https://www.conab.gov.br/info-agro/safras/serie-historica-das-safras"
METRICAS=(
    "area_plantada_mil_ha",
    "area_em_producao_mil_ha",
    "area_formacao_mil_ha",
    "area_colhida_mil_ha",
    "producao_mil_ton",
    "produtividade_kg_ha",
)
SAFRA=re.compile(r"^(20[0-9]{2})/([0-9]{2})$")


class SerieConabNaoHomologada(ValueError):
    pass


def decimal_historico(valor, nome):
    if valor is None or (isinstance(valor,float) and valor != valor):
        return None
    if isinstance(valor,str) and valor.strip() in ("", "<NA>"):
        return None
    if isinstance(valor,bool):
        raise SerieConabNaoHomologada(f"{nome}: booleano não é métrica")
    try:
        n=Decimal(str(valor))
    except (InvalidOperation,TypeError,ValueError) as exc:
        raise SerieConabNaoHomologada(f"{nome}: formato não numérico") from exc
    if not n.is_finite() or n < 0 or n > Decimal("10000000000"):
        raise SerieConabNaoHomologada(f"{nome}: valor fora do domínio")
    return format(n,"f")


def normalizar_historico(registros,meta,produto,*,inicio=2022,fim=2025,
                         coletado_em=None):
    if produto not in ("soja","milho") or not 2010 <= inicio <= fim <= 2026 or fim-inicio>11:
        raise ValueError("Escopo de consulta CONAB fora do piloto")
    if not meta or str(getattr(meta,"source","")).lower()!=FONTE:
        raise SerieConabNaoHomologada("Proveniência da série CONAB incorreta")
    origem_selecionada=getattr(meta,"selected_source",None)
    if origem_selecionada and str(origem_selecionada).lower()!=FONTE:
        raise SerieConabNaoHomologada("Fallback histórico não autorizado")
    if not isinstance(registros,list) or not registros:
        raise SerieConabNaoHomologada("Sem observações históricas")
    agora=coletado_em or datetime.now(timezone.utc)
    if agora.tzinfo is None:
        raise SerieConabNaoHomologada("Horário da coleta sem timezone")
    saida=[]
    seen=set()
    for r in registros:
        if not isinstance(r,dict) or str(r.get("produto","")).strip().lower()!=produto:
            raise SerieConabNaoHomologada("Produto da linha diverge da fonte")
        if str(r.get("uf","")).upper()!="MT":
            raise SerieConabNaoHomologada("UF diferente de MT")
        safra=str(r.get("safra","")).strip()
        match=SAFRA.fullmatch(safra)
        if not match:
            raise SerieConabNaoHomologada("Safra histórica malformada")
        year=int(match.group(1))
        if int(match.group(2))!=(year+1)%100 or not inicio<=year<=fim:
            raise SerieConabNaoHomologada("Safra histórica fora da consulta")
        if safra in seen:
            raise SerieConabNaoHomologada("Mais de um agregado histórico na mesma safra")
        seen.add(safra)
        metrics={k:decimal_historico(r.get(k),k) for k in METRICAS}
        if all(metrics[k] is None for k in ("area_plantada_mil_ha","producao_mil_ton","produtividade_kg_ha")):
            raise SerieConabNaoHomologada("Não há medida histórica principal")
        regiao=r.get("regiao")
        if regiao is not None and not isinstance(regiao,str):
            raise SerieConabNaoHomologada("Região inválida")
        saida.append({
            "fonte":"CONAB",
            "origin_kind":FONTE,
            "produto":produto,
            "uf":"MT",
            "safra":safra,
            "regiao":regiao.strip() if regiao else None,
            "metricas":metrics,
            "competencia":safra,
            "data_publicacao":None,
            "data_referencia":None,
            "data_coleta":agora.isoformat(),
            "natureza":"INFORMADO",
            "source_url":URL,
            "parser_version":"agrobr-2.0.0-historico-v1",
        })
    return sorted(saida,key=lambda x:x["safra"])
