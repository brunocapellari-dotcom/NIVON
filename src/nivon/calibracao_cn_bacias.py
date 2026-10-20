"""Calibração retrospectiva SCS-CN: train temporal + holdout de eventos.

Ajusta um CN de bacia como baseline físico simplificado. Eventos precisam
ter chuva AREAL e profundidade de escoamento observada, ambas documentadas.
Não treinamos sob dados após o corte. Eventos no holdout não selecionam CN.
Não inferir previsibilidade de chuva, cheias ou navegabilidade dessa calibração.
"""
from __future__ import annotations
from datetime import datetime,timezone
from math import isfinite,sqrt
from .hidrologia_chuva_vazao import escoamento_scs_cn

class ErroCalibracaoBacia(ValueError):
    pass

def _time(s):
    if not isinstance(s,str) or "T" not in s:
        raise ErroCalibracaoBacia("eventos exigem instante com fuso")
    try:d=datetime.fromisoformat(s.replace("Z","+00:00"))
    except ValueError as e:raise ErroCalibracaoBacia("instante inválido") from e
    if d.tzinfo is None or d.utcoffset() is None:
        raise ErroCalibracaoBacia("instante sem timezone")
    return d.astimezone(timezone.utc)

def _float(x,label,lower=None,upper=None):
    if type(x) not in (float,int) or not isfinite(x):
        raise ErroCalibracaoBacia(label+": número inválido")
    x=float(x)
    if lower is not None and x<lower or upper is not None and x>upper:
        raise ErroCalibracaoBacia(label+": fora de limites")
    return x

def _nse(obs,pred):
    m=sum(obs)/len(obs)
    den=sum((o-m)**2 for o in obs)
    return 1-sum((o-p)**2 for o,p in zip(obs,pred))/den if den>0 else None

def calibrar_cn_historico(*,eventos,treino_ate,cn_candidatos,
                         fracao_abstracao_inicial,
                         bacia_id,fonte_solo,fonte_chuva,
                         minimo_treino=20,minimo_teste=8):
    """Candidate grid, temporal train split and untouched holdout evaluation.

    Considers one event per date. An event whose data was not published by
    the cutoff can NEVER train, even when the observed event is earlier.
    Test data never tunes CN. Metrics compare with train-only mean baseline.
    """
    if not all(isinstance(v,str) and len(v.strip())>=8 for v in
               (bacia_id,fonte_solo,fonte_chuva)):
        raise ErroCalibracaoBacia("bacia e evidências obrigatórias")
    cut=_time(treino_ate)
    lam=_float(fracao_abstracao_inicial,"lambda",0,1)
    if (not isinstance(eventos,(tuple,list)) or len(eventos)>100000
        or type(minimo_treino) is not int or type(minimo_teste) is not int
        or minimo_treino<20 or minimo_teste<8):
        raise ErroCalibracaoBacia("limites mínimos de calibração 20+8 eventos")
    if not isinstance(cn_candidatos,(list,tuple)) or not 2<=len(cn_candidatos)<=200:
        raise ErroCalibracaoBacia("grade de CN explícita com 2 a 200 candidatos")
    cns=[_float(x,"CN",30,100) for x in cn_candidatos]
    if len(set(cns))!=len(cns):
        raise ErroCalibracaoBacia("CN repetido")
    training=[];holdout=[];seen=set()
    last_date=None
    for row in eventos:
        if not isinstance(row,dict):
            raise ErroCalibracaoBacia("observação não estruturada")
        day=_time(row.get("evento_em"))
        observed_at=_time(row.get("publicado_em"))
        rain_at=_time(row.get("chuva_publicada_em"))
        if observed_at<day or rain_at<day:
            raise ErroCalibracaoBacia("publicação anterior à medição")
        if last_date is not None and day<=last_date:
            raise ErroCalibracaoBacia("eventos duplicados ou desordenados")
        last_date=day
        if row.get("qualidade")!="APROVADO":
            raise ErroCalibracaoBacia("evento sem QC aprovado")
        p=_float(row.get("chuva_areal_mm"),"chuva de evento",0,2000)
        q=_float(row.get("escoamento_observado_mm"),"escoamento observado",0,2000)
        if q>p+1e-8:
            raise ErroCalibracaoBacia("escoamento direto maior que chuva areal")
        pair=(day,p,q)
        if day<=cut and observed_at<=cut and rain_at<=cut:
            training.append(pair)
        elif day>cut:
            holdout.append(pair)
        # Events <=cut whose report only became available later are excluded.
    if len(training)<minimo_treino or len(holdout)<minimo_teste:
        raise ErroCalibracaoBacia("sem treino temporal ou teste posterior suficiente")
    def simulated(cn,items):
        return [escoamento_scs_cn(
            chuva_evento_mm=p,numero_curva=cn,area_bacia_km2=1.,
            fracao_abstracao_inicial=lam,
            fonte_cn=fonte_solo,fonte_chuva=fonte_chuva
        )["escoamento_direto_estimado_mm"] for _,p,_ in items]
    truth=[r[2] for r in training]
    baseline=sum(truth)/len(truth)
    scores=[]
    for cn in cns:
        pred=simulated(cn,training)
        rmse=sqrt(sum((o-p)**2 for o,p in zip(truth,pred))/len(truth))
        scores.append((rmse,cn))
    train_rmse,selected=min(scores)
    test_truth=[r[2] for r in holdout]
    test_pred=simulated(selected,holdout)
    test_mae=sum(abs(o-p) for o,p in zip(test_truth,test_pred))/len(holdout)
    test_rmse=sqrt(sum((o-p)**2 for o,p in zip(test_truth,test_pred))/len(holdout))
    baseline_rmse=sqrt(sum((o-baseline)**2 for o in test_truth)/len(holdout))
    return {
        "bacia_id":bacia_id,"corte_treino":cut.isoformat(),
        "cn_selecionado":selected,"lambda":lam,
        "eventos_treino":len(training),"eventos_holdout":len(holdout),
        "rmse_treino_mm":train_rmse,"rmse_holdout_mm":test_rmse,
        "mae_holdout_mm":test_mae,
        "nse_holdout":_nse(test_truth,test_pred),
        "baseline_medio_treino_mm":baseline,
        "baseline_rmse_holdout_mm":baseline_rmse,
        "skill_mse_baseline":1-test_rmse**2/baseline_rmse**2 if baseline_rmse>0 else None,
        "candidatos_avaliados":len(cns),
        "fonte_solo":fonte_solo,"fonte_chuva":fonte_chuva,
        "classificacao":"CN_CALIBRACAO_RETROSPECTIVA_BACIA",
        "promocao_automatica":False,
        "limites":"Sem CN condicionado à umidade anterior, uso do solo ou sazonalidade; "
                  "baseline é média dos eventos de treino, NÃO previsão de cheias. "
                  "Teste é retrospectivo com chuva observada, não previsão meteorológica."}
