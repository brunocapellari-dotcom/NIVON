"""Auditoria de séries e previsões ambientais com vintages e baseline.

Não treina modelos nem atesta precisão sem histórico real. Datas com TZ
são necessárias: previsão deve existir antes do evento; features usadas
devem ter sido publicadas antes da emissão (defesa contra look-ahead).
"""
from __future__ import annotations
from datetime import datetime,timezone
from math import isfinite,sqrt

class ErroAvaliacaoAmbiental(ValueError):
    pass

def _v(v,n,menor=None,maior=None):
    if type(v) not in (int,float) or not isfinite(v):
        raise ErroAvaliacaoAmbiental(n+" não é número finito")
    x=float(v)
    if menor is not None and x<menor or maior is not None and x>maior:
        raise ErroAvaliacaoAmbiental(n+" excede limites")
    return x

def _data(v,n):
    if not isinstance(v,str) or "T" not in v:
        raise ErroAvaliacaoAmbiental(n+" exige ISO com hora")
    try:d=datetime.fromisoformat(v.replace("Z","+00:00"))
    except ValueError as exc:raise ErroAvaliacaoAmbiental(n+" inválido") from exc
    if d.tzinfo is None or d.utcoffset() is None:
        raise ErroAvaliacaoAmbiental(n+" exige fuso")
    return d.astimezone(timezone.utc)

def validar_hindcast_ambiental(*,registros,fonte_modelo,
                              variavel,unidade,estacao_id,
                              horizonte_horas):
    """Walk-forward em registros já gerados antes do evento, sem treino interno.

    Campos obrigatórios: emitido_em, valido_em, feature_publicada_ate,
    observado_publicado_em, observado, previsto, baseline, qualidade.
    Validação verifica apenas timestamps informados; integridade da origem
    dos features e vintage do próprio treinamento requer auditoria externa.
    """
    if not isinstance(registros,(list,tuple)) or not 20<=len(registros)<=100000:
        raise ErroAvaliacaoAmbiental("amostra mínima de 20 previsões por horizonte")
    for x in (fonte_modelo,variavel,unidade,estacao_id):
        if not isinstance(x,str) or not x.strip():
            raise ErroAvaliacaoAmbiental("fonte, variável, unidade e estação obrigatórias")
    horizon=_v(horizonte_horas,"horizonte",1,720)
    seen=set();obs=[];pr=[];base=[]
    for r in registros:
        if not isinstance(r,dict):
            raise ErroAvaliacaoAmbiental("registro não é objeto")
        issue=_data(r.get("emitido_em"),"emissão")
        valid=_data(r.get("valido_em"),"validade")
        used=_data(r.get("feature_publicada_ate"),"última publicação feature")
        published=_data(r.get("observado_publicado_em"),"publicação observação")
        if (used>issue or valid<=issue or published<valid or
             abs((valid-issue).total_seconds()/3600-horizon)>1e-6):
            raise ErroAvaliacaoAmbiental("fuga temporal, horizonte misto ou medição ainda futura")
        ident=(issue,valid)
        if ident in seen:
            raise ErroAvaliacaoAmbiental("previsão duplicada para issue/validade")
        seen.add(ident)
        if r.get("qualidade")!="APROVADO":
            raise ErroAvaliacaoAmbiental("medição sem QC aprovado")
        o=_v(r.get("observado"),"observado")
        p=_v(r.get("previsto"),"previsto")
        b=_v(r.get("baseline"),"baseline")
        if variavel in ("PRECIPITACAO_MM","VAZAO_M3_S","ET0_MM") and min(o,p,b)<0:
            raise ErroAvaliacaoAmbiental("quantidade física negativa")
        obs.append(o);pr.append(p);base.append(b)
    err=[p-o for p,o in zip(pr,obs)]
    be=[b-o for b,o in zip(base,obs)]
    mse=sum(x*x for x in err)/len(err)
    mse_base=sum(x*x for x in be)/len(be)
    return {"estacao_id":estacao_id,"variavel":variavel,"unidade":unidade,
            "horizonte_horas":horizon,"n":len(err),
            "mae":sum(abs(x) for x in err)/len(err),
            "rmse":sqrt(mse),"bias":sum(err)/len(err),
            "baseline_rmse":sqrt(mse_base),
            "skill_mse_contra_baseline":1-mse/mse_base if mse_base else None,
            "fonte_modelo":fonte_modelo,
            "classificacao":"AVALIACAO_HINDCAST_COM_GATES_TEMPORAIS",
            "homologado":False,
            "limitacao":"Não verifica features remotas, dados corrigidos após revisão "
                       "nem independência espacial das estações; requer auditoria e holdout real."}

def confrontar_grade_com_estacao(*,pares_diarios,estacao_id,
                                produto_grade,distancia_centro_grade_km,
                                fonte_medida,metrica,unidade):
    """Erro de grade climática contra estação somente em dias pareados e QC bom.

    Distância precisa ser informada por georreferenciamento externo.
    """
    if not isinstance(pares_diarios,(list,tuple)) or not 30<=len(pares_diarios)<=50000:
        raise ErroAvaliacaoAmbiental("mínimo de 30 dias observados coincidentes")
    for k in (estacao_id,produto_grade,fonte_medida,metrica,unidade):
        if not isinstance(k,str) or not k.strip():
            raise ErroAvaliacaoAmbiental("fonte, estação, produto e variável obrigatórios")
    dist=_v(distancia_centro_grade_km,"distância geográfica",0,150)
    obs=[];mod=[];seen=set()
    for row in pares_diarios:
        if not isinstance(row,dict):
            raise ErroAvaliacaoAmbiental("par diário inválido")
        date=row.get("data")
        try:
            from datetime import date as Data
            dia=Data.fromisoformat(date)
        except (ValueError,TypeError) as exc:
            raise ErroAvaliacaoAmbiental("data de competência inválida") from exc
        if dia in seen:raise ErroAvaliacaoAmbiental("data repetida")
        seen.add(dia)
        if row.get("qualidade_estacao")!="APROVADO":
            raise ErroAvaliacaoAmbiental("QC de estação não aprovado")
        a=_v(row.get("valor_estacao"),"estação")
        b=_v(row.get("valor_grade"),"grade")
        if metrica in ("CHUVA_DIA_MM","ET0_MM_DIA") and (a<0 or b<0):
            raise ErroAvaliacaoAmbiental("quantidade negativa")
        obs.append(a);mod.append(b)
    err=[m-o for m,o in zip(mod,obs)]
    return {"estacao":estacao_id,"produto_grade":produto_grade,"n":len(err),
            "distancia_grade_km":dist,
            "mae":sum(abs(x) for x in err)/len(err),
            "rmse":sqrt(sum(x*x for x in err)/len(err)),
            "bias":sum(err)/len(err),
            "fonte_estacao":fonte_medida,"metrica":metrica,"unidade":unidade,
            "classificacao":"VALIDACAO_GRADE_ESTACAO_PAREADA",
            "limitacao":"Pontos/grades têm suportes espaciais diferentes; não comprova "
                       "aptidão local sem escala, altitude, relevo e amostragem espacial."}
