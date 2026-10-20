"""Auditoria preditiva com vintages de dados e validação temporal de verdade.

Diferente de walk-forward de série FINAL, reconstrói em cada origem exatamente
as observações cujas publicações E coletas já existiam naquele momento.
Não publica previsões nem homologa um modelo. Sem rede e sem SQL dinâmico.
"""
from __future__ import annotations

from datetime import datetime, timezone
from math import isfinite
from typing import Callable

from .previsoes_bibliotecas import validar_serie_mensal, ErroPrevisao


class ErroVintage(ErroPrevisao):
    pass


def _instante(valor: str) -> datetime:
    if not isinstance(valor,str):
        raise ErroVintage("timestamp ausente")
    try:
        x=datetime.fromisoformat(valor.replace("Z","+00:00"))
    except ValueError as exc:
        raise ErroVintage("timestamp inválido") from exc
    if x.tzinfo is None or x.utcoffset() is None:
        raise ErroVintage("timestamp precisa ter fuso")
    return x.astimezone(timezone.utc)


def _mes(m: str) -> int:
    if not isinstance(m, str) or len(m) != 7:
        raise ErroVintage("competência YYYY-MM obrigatória")
    try:
        d=datetime.strptime(m,"%Y-%m")
    except ValueError as exc:
        raise ErroVintage("competência inválida") from exc
    return d.year*12+d.month


def _mensal(m: int) -> str:
    return "%04d-%02d"%((m-1)//12,(m-1)%12+1)


def validar_vintages(registros: list[dict]) -> tuple[list[dict],str]:
    if not isinstance(registros,list) or not 24<=len(registros)<=200_000:
        raise ErroVintage("24+ observações com vintage são necessárias")
    fontes=set()
    hashes=set()
    saida=[]
    for item in registros:
        if not isinstance(item,dict):
            raise ErroVintage("registro não estruturado")
        try:
            fonte=item["fonte_id"]
            periodo=item["competencia"]
            n=item["valor"]
            publicado=_instante(item["publicacao"])
            coleta=_instante(item["coleta"])
            evidencia=item["evidencia"]
        except KeyError as exc:
            raise ErroVintage("falta evidência ou data") from exc
        if not isinstance(fonte,str) or not fonte or len(fonte)>100:
            raise ErroVintage("fonte inválida")
        if not isinstance(evidencia,str) or not evidencia or len(evidencia)>256:
            raise ErroVintage("evidência inválida")
        mes=_mes(periodo)
        if type(n) not in (int,float) or not isfinite(n) or n<0:
            raise ErroVintage("observação não finita/negativa")
        if coleta < publicado:
            raise ErroVintage("coleta anterior à publicação")
        chave=(fonte,mes,publicado,coleta)
        if chave in hashes:
            raise ErroVintage("vintage temporal duplicada")
        hashes.add(chave)
        fontes.add(fonte)
        saida.append({"mes":mes,"competencia":periodo,"valor":float(n),
                      "publicacao":publicado,"coleta":coleta,"evidencia":evidencia})
    if len(fontes)!=1:
        raise ErroVintage("fontes mistas sem contrato de reconciliação")
    return saida, fontes.pop()


def selecionar_asof(registros: list[dict], *, corte: str,
                   ate_competencia: str | None = None) -> list[tuple[str,float]]:
    """Reconstrói as vintages disponíveis; nunca usa revisão posterior."""
    data=_instante(corte)
    lim=_mes(ate_competencia) if ate_competencia is not None else None
    escolhidas={}
    for item in registros:
        if item["publicacao"]>data or item["coleta"]>data:
            continue
        mes=item["mes"]
        if lim is not None and mes>lim:
            continue
        anterior=escolhidas.get(mes)
        if anterior is None or (item["publicacao"],item["coleta"])>(anterior["publicacao"],anterior["coleta"]):
            escolhidas[mes]=item
    return [(_mensal(m),escolhidas[m]["valor"]) for m in sorted(escolhidas)]


def avaliar_asof(
    registros: list[dict], *,
    cortes: list[dict], backend: Callable,
) -> dict:
    """Avalia origens históricas e baseline sazonal, falhando fechado.

    cortes: [{"competencia_alvo":"YYYY-MM","origem":"ISO TZ",
              "avaliacao":"ISO TZ"},...]
    A data de avaliação deve ser posterior ao mês-alvo; as revisões pós-origem
    não entram no treinamento e somente a vintage existente na avaliação mede y.
    """
    rows,source=validar_vintages(registros)
    if not isinstance(cortes,list) or not 3<=len(cortes)<=36:
        raise ErroVintage("exigir 3 a 36 origens históricas")
    if not callable(backend):
        raise ErroVintage("backend explícito obrigatório")
    seen=set()
    resultados=[]
    for f in cortes:
        if not isinstance(f,dict) or set(f)!={"competencia_alvo","origem","avaliacao"}:
            raise ErroVintage("fold inválido")
        target=f["competencia_alvo"]
        alvo_mes=_mes(target)
        if alvo_mes in seen:
            raise ErroVintage("alvo repetido")
        seen.add(alvo_mes)
        origem=_instante(f["origem"])
        avaliacao=_instante(f["avaliacao"])
        dt=datetime.strptime(target,"%Y-%m")
        from calendar import monthrange
        fim_mes=datetime(dt.year,dt.month,monthrange(dt.year,dt.month)[1],23,59,59,tzinfo=timezone.utc)
        inicio_mes=datetime(dt.year,dt.month,1,tzinfo=timezone.utc)
        if not origem<inicio_mes or not avaliacao>fim_mes:
            raise ErroVintage("origem deve anteceder alvo e avaliação suceder mês-alvo")
        treino=selecionar_asof(rows,corte=origem.isoformat(),ate_competencia=_mensal(alvo_mes-1))
        treino=validar_serie_mensal(treino)
        if _mes(treino[-1][0])!=alvo_mes-1:
            raise ErroVintage("série tem atraso; previsão de 1 mês não cobre o alvo")
        observacoes=selecionar_asof(rows,corte=avaliacao.isoformat(),ate_competencia=target)
        real=next((v for period,v in observacoes if period==target),None)
        if real is None:
            raise ErroVintage("valor de alvo ainda não observável no corte de avaliação")
        previsto=backend(treino,1)
        if (not isinstance(previsto,(list,tuple)) or len(previsto)!=1
            or type(previsto[0]) not in (int,float)
            or not isfinite(previsto[0]) or previsto[0]<0):
            raise ErroVintage("saída de previsão fora do domínio")
        sazonal=treino[-12][1]
        resultados.append({
            "alvo":target,"origem":origem.isoformat(),
            "avaliacao":avaliacao.isoformat(),
            "n_treino":len(treino),"observado":real,
            "previsao":float(previsto[0]),"referencia_sazonal":sazonal,
            "erro_absoluto":abs(real-previsto[0]),
            "erro_sazonal":abs(real-sazonal),
        })
    mae=sum(f["erro_absoluto"] for f in resultados)/len(resultados)
    mae_s=sum(f["erro_sazonal"] for f in resultados)/len(resultados)
    return {
        "status":"VALIDACAO_VINTAGE_EXECUTADA_NAO_HOMOLOGADA",
        "fonte":source,
        "folds":resultados,
        "mae_modelo":mae,"mae_referencia_sazonal":mae_s,
        "superou_referencia":mae<mae_s,
        "n_origens":len(resultados),
        "look_ahead_blocked":True,
        "licenca_confirmada":False,
        "publicar_previsao":False,
        "requisitos_pendentes":[
            "histórico real e vintages validadas",
            "licença de uso e redistribuição do dado",
            "comparação temporal independente com holdout",
            "incerteza e estabilidade em múltiplas safras",
            "aprovação da auditoria de domínio",
        ],
    }
