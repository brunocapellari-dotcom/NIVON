"""Avaliação rigorosa, mas OFFLINE, de previsões de produtividade por safra.

As métricas só são diagnósticas: rótulos FORA_AMOSTRA e hashes fornecidos
não provam por si mesmos treinamento sem fuga, direito de uso ou precisão real.
Unidade invariável kg/ha, folds agrupados por ano agrícola (não por talhão).
Bootstrap em blocos de dois anos, com seed fixa, SEM pretensão de CI exato
sob dependência climática longa, seleção múltipla ou eventos extremos.
"""
from __future__ import annotations

from datetime import datetime,timezone
from hashlib import sha256
from math import isfinite, sqrt
from random import Random
import re


class ErroBacktestSafra(ValueError):
    pass


_CULTURAS=frozenset({"SOJA","MILHO","TRIGO","ALGODAO","SORGO","CANA","GERGELIM"})
_HASH=re.compile(r"[0-9a-f]{64}\Z")
_IBGE=re.compile(r"[1-9][0-9]{6}\Z")


def _data(t,n):
    if not isinstance(t,str) or "T" not in t:
        raise ErroBacktestSafra(n+": timestamp ISO com fuso obrigatório")
    try:d=datetime.fromisoformat(t.replace("Z","+00:00"))
    except ValueError as exc:raise ErroBacktestSafra(n+": data inválida") from exc
    if d.tzinfo is None or d.utcoffset() is None:
        raise ErroBacktestSafra(n+": fuso ausente")
    return d.astimezone(timezone.utc)


def _num(x,n,*,maximum=300000):
    if type(x) not in (int,float) or not isfinite(x) or x<0 or x>maximum:
        raise ErroBacktestSafra(n+": valor físico inválido")
    return float(x)


def _metricas(pares):
    n=len(pares)
    mse=sum(e*e for e,_ in pares)/n
    mae=sum(abs(e) for e,_ in pares)/n
    mseb=sum(b*b for _,b in pares)/n
    maeb=sum(abs(b) for _,b in pares)/n
    return {"mae":mae,"rmse":sqrt(mse),"mae_baseline":maeb,
            "rmse_baseline":sqrt(mseb),
            "ganho_mae":None if maeb==0 else 1-mae/maeb,
            "ganho_rmse":None if mseb==0 else 1-sqrt(mse)/sqrt(mseb)}


def _quantil(x,p):
    q=sorted(x)
    pos=(len(q)-1)*p
    left=int(pos);right=min(len(q)-1,left+1)
    return q[left]+(q[right]-q[left])*(pos-left)


def avaliar_backtest_safra(
    *,registros:list[dict],cultura:str,modelo_id:str,
    horizonte_min_dias:int,horizonte_max_dias:int,
    repeticoes_bootstrap:int=500,semente:int=2026,
) -> dict:
    """Audita folds históricos que já foram emitidos, sem treinar.

    Campos por fold: municipio_ibge,ano_colheita,origem,feature_disponivel_em,
    baseline_disponivel_em,modelo_gerado_em,colheita_encerrada_em,
    observado_publicado_em,observado_coletado_em,ultima_safra_treinada,
    observado_kg_ha,previsto_kg_ha,baseline_kg_ha,observado_raw_sha256,
    previsao_sha256,estado_teste='FORA_AMOSTRA_DECLARADO'.
    """
    if cultura not in _CULTURAS or not isinstance(modelo_id,str) or not 3<=len(modelo_id)<=120:
        raise ErroBacktestSafra("cultura/modelo desconhecido")
    if (type(horizonte_min_dias) is not int or type(horizonte_max_dias) is not int
        or not 1<=horizonte_min_dias<=horizonte_max_dias<=500):
        raise ErroBacktestSafra("horizonte inválido")
    if (type(repeticoes_bootstrap) is not int or not 200<=repeticoes_bootstrap<=2000
        or type(semente) is not int or not 0<=semente<=2**32-1):
        raise ErroBacktestSafra("configuração de bootstrap inválida")
    if not isinstance(registros,list) or not 30<=len(registros)<=100000:
        raise ErroBacktestSafra("mínimo 30 folds declarados, sem amostra artificial")
    byyear={};bymuni={};seen=set();all_pairs=[]
    for ix,row in enumerate(registros):
        if not isinstance(row,dict):
            raise ErroBacktestSafra(f"linha {ix}: não é objeto")
        try:
            municipio=row["municipio_ibge"]
            ano=row["ano_colheita"]
            if not isinstance(municipio,str) or not _IBGE.fullmatch(municipio):
                raise ErroBacktestSafra("município IBGE deve preservar sete dígitos")
            if type(ano) is not int or not 2000<=ano<=2100:
                raise ErroBacktestSafra("ano da colheita inválido")
            if (municipio,ano) in seen:
                raise ErroBacktestSafra("mesma observação ano/município duplicada")
            seen.add((municipio,ano))
            issue=_data(row["origem"],"origem")
            latest=_data(row["feature_disponivel_em"],"feature")
            baseline_time=_data(row["baseline_disponivel_em"],"baseline")
            generated=_data(row["modelo_gerado_em"],"modelo")
            harvest=_data(row["colheita_encerrada_em"],"colheita")
            published=_data(row["observado_publicado_em"],"publicação")
            collected=_data(row["observado_coletado_em"],"coleta")
            train=row["ultima_safra_treinada"]
            if type(train) is not int or train>=ano:
                raise ErroBacktestSafra("treino inclui safra-alvo ou metadado inválido")
            if not (latest<=issue and baseline_time<=issue and generated<=issue
                    and issue<harvest<=published<=collected
                    and harvest.year==ano):
                raise ErroBacktestSafra("fuga temporal ou publicação impossível")
            lead=(harvest-issue).total_seconds()/86400
            if not horizonte_min_dias<=lead<=horizonte_max_dias:
                raise ErroBacktestSafra("horizonte incompatível com experimento")
            if row["estado_teste"]!="FORA_AMOSTRA_DECLARADO":
                raise ErroBacktestSafra("teste independente não declarado")
            for field in ("observado_raw_sha256","previsao_sha256"):
                h=row[field]
                if not isinstance(h,str) or not _HASH.fullmatch(h):
                    raise ErroBacktestSafra("hash de proveniência ausente")
            obs=_num(row["observado_kg_ha"],"rendimento observado")
            pred=_num(row["previsto_kg_ha"],"rendimento previsto")
            base=_num(row["baseline_kg_ha"],"rendimento baseline")
            err=pred-obs;errb=base-obs
            byyear.setdefault(ano,[]).append((err,errb))
            bymuni.setdefault(municipio,[]).append((err,errb))
            all_pairs.append((err,errb))
        except KeyError as exc:
            raise ErroBacktestSafra(f"linha {ix}: campo obrigatório ausente {exc}") from exc
    years=sorted(byyear)
    if len(years)<8 or len(bymuni)<3:
        return {"status":"REPROVADO_COBERTURA_HISTORICA", "anos":len(years),
                "municipios":len(bymuni),"n":len(registros),"habilita_previsao":False}
    if any(len(byyear[y])<2 for y in years):
        return {"status":"REPROVADO_COBERTURA_POR_ANO","anos":len(years),
                "municipios":len(bymuni),"n":len(registros),"habilita_previsao":False}
    # Estatísticas globais por observação + mesma ponderação por ANO para
    # intervalos, evitando que um ano com muitos municípios domine o bootstrap.
    global_metrics=_metricas(all_pairs)
    each_year=[_metricas(byyear[y]) for y in years]
    years_errors=[(
        sum(abs(e) for e,_ in byyear[y])/len(byyear[y]),
        sum(abs(b) for _,b in byyear[y])/len(byyear[y])
    ) for y in years]
    equal_year_mae=sum(x for x,_ in years_errors)/len(years)
    equal_year_base=sum(y for _,y in years_errors)/len(years)
    equal_year_gain=None if equal_year_base==0 else 1-equal_year_mae/equal_year_base
    rng=Random(semente)
    n=len(years);block=2;skills=[]
    for _ in range(repeticoes_bootstrap):
        positions=[]
        while len(positions)<n:
            start=rng.randrange(n)
            positions.extend((start+i)%n for i in range(block))
        indices=positions[:n]
        m=sum(years_errors[j][0] for j in indices)/n
        b=sum(years_errors[j][1] for j in indices)/n
        if b>0:skills.append(1-m/b)
    ci=[_quantil(skills,.025),_quantil(skills,.975)] if len(skills)>=repeticoes_bootstrap*.95 else None
    per_city={}
    for city,values in sorted(bymuni.items()):
        per_city[city]={"n":len(values),**_metricas(values)} if len(values)>=5 else {
            "n":len(values),"estado":"SEM_AMOSTRA_PARA_METRICA_LOCAL"}
    return {
        "status":"AUDITORIA_TEMPORAL_DECLARADA_NAO_HOMOLOGADA",
        "cultura":cultura,"modelo":modelo_id,"unidade":"kg/ha",
        "n":len(registros),"anos":len(years),"primeiro_ano":years[0],
        "ultimo_ano":years[-1],"municipios":len(bymuni),
        "horizonte_min_dias":horizonte_min_dias,
        "horizonte_max_dias":horizonte_max_dias,
        "global":global_metrics,
        "ganho_mae_anos_iguais":equal_year_gain,
        "intervalo_bootstrap_ganho_mae_anos_iguais":ci,
        "bootstrap":{"bloco_anos":block,"repeticoes":repeticoes_bootstrap,
            "semente":semente,"suposicao":"anos/blocos circularizados, aproximação exploratória"},
        "por_ano":[{"ano":year,"n":len(byyear[year]),**e} for year,e in zip(years,each_year)],
        "por_municipio":per_city,
        "superou_baseline_global_mae_rmse": (
            global_metrics["mae"]<global_metrics["mae_baseline"] and
            global_metrics["rmse"]<global_metrics["rmse_baseline"]),
        "limite_inferior_ganho_positivo":bool(ci is not None and ci[0]>0),
        "habilita_previsao":False,
        "auditoria_externa_necessaria": [
            "comprovar edições reais point-in-time de features, baseline e alvo",
            "verificar hashes RAW e vazamento no processo de treino",
            "avaliar drift, dependência interanual, múltiplas comparações e holdout espacial",
            "validar licenças e metas de cobertura por cultura/região/horizonte",
        ],
    }
