"""Probabilistic weather verification for fixed lead times and point locations.

Brier score for threshold events and empirical ensemble CRPS, exactly
weighted as sample mean |member-observation| minus pairwise dispersion.
NO training, production score or forecast publication occurs here.
Publication vintages and forecast issue times are mandatory; probability
calibration is tested independently from physical accuracy.
"""
from __future__ import annotations
from datetime import datetime, timezone
from math import isfinite, sqrt
from statistics import mean

class ErroProbabilistico(ValueError):
    pass

def _n(v, name, minimum=None, maximum=None):
    if type(v) not in (float,int) or not isfinite(v):
        raise ErroProbabilistico(name+": número finito obrigatório")
    x=float(v)
    if minimum is not None and x<minimum or maximum is not None and x>maximum:
        raise ErroProbabilistico(name+": fora dos limites")
    return x

def _date(v, name):
    if not isinstance(v,str) or "T" not in v:
        raise ErroProbabilistico(name+": timestamp ISO obrigatório")
    try:
        parsed=datetime.fromisoformat(v.replace("Z","+00:00"))
    except ValueError as exc:
        raise ErroProbabilistico(name+": timestamp inválido") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ErroProbabilistico(name+": fuso obrigatório")
    return parsed.astimezone(timezone.utc)

def _value(v, variable):
    low,high = {
        "CHUVA_ACUMULADA_MM":(0,5000),
        "VAZAO_M3_S":(0,2e7),
        "TMAX_C":(-90,70),
        "TMIN_C":(-90,70)
    }[variable]
    return _n(v,variable,low,high)

def crps_ensemble(observado, membros):
    """Fairness correction intentionally NOT applied: ordinary ensemble CRPS.

    CRPS = mean|x-y| - 1/(2*n^2)*sum_ij|xi-xj|;
    sorted representation avoids quadratic work, making large hindcasts cheap.
    """
    if not isinstance(membros,(list,tuple)) or not 2<=len(membros)<=200:
        raise ErroProbabilistico("ensemble requer 2 a 200 membros")
    y=_n(observado,"observado")
    xs=sorted(_n(v,"membro") for v in membros)
    n=len(xs)
    absolute=sum(abs(x-y) for x in xs)/n
    pairwise=sum((2*i-n+1)*x for i,x in enumerate(xs))/(n*n)
    score=absolute-pairwise
    return max(0.,score) if abs(score)<1e-10 else score

def avaliar_ensemble(*,registros,variavel,limiar_evento,
                     horizonte_horas,modelo_id,local_id,
                     minimo=30):
    """Out-of-sample verification ONLY if provided records are genuinely held out.

    Expected: emitido_em, valido_em, feature_publicada_ate, obs_publicado_em,
    observado, membros, prob_climatologica, qc, modo_validacao.
    Strictly excludes hindcasts generated after the valid time and features
    published after forecast issue; independent audit needed to prove no train leak.
    """
    if variavel not in {"CHUVA_ACUMULADA_MM","VAZAO_M3_S","TMAX_C","TMIN_C"}:
        raise ErroProbabilistico("variável/escala incompatível")
    if not all(isinstance(v,str) and 3<=len(v.strip())<=120 for v in (modelo_id,local_id)):
        raise ErroProbabilistico("modelo e local canônicos obrigatórios")
    threshold=_value(limiar_evento,variavel)
    lead=_n(horizonte_horas,"horizonte",1,720)
    if type(minimo) is not int or not 30<=minimo<=10000:
        raise ErroProbabilistico("mínimo amostral necessita >=30")
    if not isinstance(registros,(tuple,list)) or not minimo<=len(registros)<=100000:
        raise ErroProbabilistico("amostra curta ou muito grande para avaliação")
    records=[];keys=set();bin_count=[0]*10;bin_prob=[0.]*10;bin_obs=[0.]*10
    obs_event=0;model_brier=0.;ref_brier=0.;crps=0.;spread=0.
    member_n=None
    for row in registros:
        if not isinstance(row,dict):
            raise ErroProbabilistico("registro não canônico")
        emit=_date(row.get("emitido_em"),"emissão")
        valid=_date(row.get("valido_em"),"validade")
        feature=_date(row.get("feature_publicada_ate"),"feature")
        pub=_date(row.get("obs_publicado_em"),"publicação da observação")
        if feature>emit or valid<=emit or pub<valid:
            raise ErroProbabilistico("vazamento temporal ou observação inválida")
        if abs((valid-emit).total_seconds()/3600-lead)>1e-6:
            raise ErroProbabilistico("horizonte misturado")
        key=(emit,valid)
        if key in keys:
            raise ErroProbabilistico("previsão duplicada")
        keys.add(key)
        if row.get("qc")!="APROVADO" or row.get("modo_validacao")!="FORA_AMOSTRA":
            raise ErroProbabilistico("QC reprovado ou dado treinado no teste")
        obs=_value(row.get("observado"),variavel)
        members=row.get("membros")
        if not isinstance(members,(list,tuple)) or not 2<=len(members)<=200:
            raise ErroProbabilistico("membros inexistentes")
        if member_n is None:member_n=len(members)
        if len(members)!=member_n:
            raise ErroProbabilistico("ensemble com membros faltantes")
        members=[_value(x,variavel) for x in members]
        base=_n(row.get("prob_climatologica"),"probabilidade climatológica",0,1)
        # Event convention: threshold or greater, including equality.
        event=1 if obs>=threshold else 0
        prob=sum(x>=threshold for x in members)/len(members)
        bs=(prob-event)**2
        crps+=crps_ensemble(obs,members)
        spread+=sqrt(sum((x-mean(members))**2 for x in members)/len(members))
        model_brier+=bs
        ref_brier+=(base-event)**2
        obs_event+=event
        index=min(9,int(prob*10))
        bin_count[index]+=1;bin_prob[index]+=prob;bin_obs[index]+=event
    n=len(registros)
    brier=model_brier/n
    bs_ref=ref_brier/n
    bins=[{"p_inicio":i/10,"p_fim":(i+1)/10,"n":bin_count[i],
           "prob_prevista_media":bin_prob[i]/bin_count[i] if bin_count[i] else None,
           "frequencia_observada":bin_obs[i]/bin_count[i] if bin_count[i] else None}
          for i in range(10)]
    # Small bins cannot establish reliability; do not manufacture confidence.
    bins_pouco_representativos=sum(0<c<10 for c in bin_count)
    return {"modelo":modelo_id,"local":local_id,"variavel":variavel,
            "limiar_evento":threshold,"horizonte_horas":lead,"n":n,
            "membros_por_previsao":member_n,
            "taxa_observada_evento":obs_event/n,
            "brier_score":brier,"brier_climatologia":bs_ref,
            "brier_skill_score":1-brier/bs_ref if bs_ref>0 else None,
            "crps_medio_na_unidade":crps/n,
            "dispersao_ensemble_media_na_unidade":spread/n,
            "calibracao_por_faixas":bins,
            "faixas_com_menos_10_casos":bins_pouco_representativos,
            "homologado":False,
            "estado":"DIAGNOSTICO_PROBABILISTICO_COM_GATES_ASOF",
            "limites":"Baselines por época/local devem ter vintages auditadas; "
                      "o campo FORA_AMOSTRA é declaração do chamador, não prova. "
                      "Validação de out-of-sample, cobertura, espacialidade e "
                      "independência de treino exigem auditoria adicional."}
