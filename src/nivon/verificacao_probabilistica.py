"""Verificação de previsões probabilísticas: eventos e intervalos, sem LLM."""
from __future__ import annotations
from .qualidade_cientifica import ErroCientifico, numero


def brier_probabilidade(*, probabilidades:list[float], ocorrencias:list[int],
                        evento_definido: str) -> dict:
    if not isinstance(evento_definido,str) or not evento_definido.strip():
        raise ErroCientifico("evento precisa estar definido antes da avaliação")
    if (not isinstance(probabilidades,(list,tuple))
        or not isinstance(ocorrencias,(list,tuple))
        or len(probabilidades)!=len(ocorrencias) or len(probabilidades)<10):
        raise ErroCientifico("mínimo 10 eventos pareados")
    soma=0.0
    for p,o in zip(probabilidades,ocorrencias):
        p=numero(p,"probabilidade")
        if p>1 or type(o) is not int or o not in (0,1):
            raise ErroCientifico("probabilidade fora de [0,1] ou ocorrência não binária")
        soma+=(p-o)**2
    return {"brier":soma/len(probabilidades),"pares":len(probabilidades),
            "evento":evento_definido,"status":"SCORE_SEM_HOMOLOGACAO"}


def pontuacao_quantis(*, observados:list[float],
                      quantis:list[float], estimativas:list[list[float]],
                      unidade:str) -> dict:
    """Pinball médio por quantil: estimativas[i][j] para observação i e quantil j.

    Quantis estritamente crescentes em (0,1), todas as previsões monotônicas.
    """
    if not unidade or not isinstance(quantis,list) or not isinstance(observados,list) or not isinstance(estimativas,list):
        raise ErroCientifico("unidade e arrays requeridos")
    if len(observados)<10 or len(estimativas)!=len(observados) or not quantis:
        raise ErroCientifico("métricas requerem >=10 observações e quantis")
    qs=[numero(q,"quantil") for q in quantis]
    if not all(0<q<1 for q in qs) or any(qs[i]>=qs[i+1] for i in range(len(qs)-1)):
        raise ErroCientifico("quantis únicos, em ordem estrita de 0 a 1")
    perdas=[0.0 for _ in qs]
    for observed,predict in zip(observados,estimativas):
        y=numero(observed,"observado",nao_negativo=False)
        if not isinstance(predict,(list,tuple)) or len(predict)!=len(qs):
            raise ErroCientifico("uma estimativa para cada quantil")
        row=[numero(x,"quantil_estimado",nao_negativo=False) for x in predict]
        if any(row[i]>row[i+1] for i in range(len(row)-1)):
            raise ErroCientifico("cruzamento de quantis invalida intervalo")
        for i,(q,x) in enumerate(zip(qs,row)):
            e=y-x
            perdas[i]+=max(q*e,(q-1)*e)
    return {"quantis":qs,"pinball_por_quantil":[p/len(observados) for p in perdas],
            "pinball_medio":sum(perdas)/(len(observados)*len(qs)),
            "pares":len(observados),"unidade":unidade,
            "status":"SCORE_SEM_VALIDACAO_DE_ASOF"}


def cobertura_intervalos(*, observados:list[float],
                         limites_inferiores:list[float],
                         limites_superiores:list[float],
                         nivel_nominal:float, unidade:str) -> dict:
    q=numero(nivel_nominal,"nivel_nominal")
    if not 0<q<1 or not unidade:
        raise ErroCientifico("nível nominal entre zero e um e unidade obrigatória")
    if not (isinstance(observados,list) and isinstance(limites_inferiores,list)
            and isinstance(limites_superiores,list) and len(observados)>=10
            and len(observados)==len(limites_inferiores)==len(limites_superiores)):
        raise ErroCientifico("intervalos e realizações alinhados com >=10 pares")
    acertos=0;amplitudes=0.
    for y,lo,hi in zip(observados,limites_inferiores,limites_superiores):
        y=numero(y,"observado",nao_negativo=False)
        lo=numero(lo,"limite_inferior",nao_negativo=False)
        hi=numero(hi,"limite_superior",nao_negativo=False)
        if lo>hi:raise ErroCientifico("limites cruzados")
        acertos+=lo<=y<=hi
        amplitudes+=hi-lo
    return {"cobertura_empirica":acertos/len(observados),
            "nivel_nominal":q,"desvio_cobertura":acertos/len(observados)-q,
            "amplitude_media":amplitudes/len(observados),
            "pares":len(observados),"unidade":unidade,
            "status":"ESTATISTICA_SEM_HOMOLOGACAO"}
