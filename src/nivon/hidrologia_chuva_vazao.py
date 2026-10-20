"""Modelos hidrológicos SCS-CN e Muskingum com conservação de massa.

NRCS NEH 630 ch10: escoamento direto potencial (chuva evento, CN calibrado).
USACE HEC-HMS Muskingum: propagação de vazões horárias, parâmetros K/X
calibrados por trecho e timestep. Sem geografia da bacia, CN ou vazão
observada, nenhum resultado é alerta, previsão ou disponibilidade hidroviária.
"""
from __future__ import annotations
from datetime import datetime,timezone
from math import isfinite

class ErroChuvaVazao(ValueError):
    pass

def _v(x,n,minimum=None,maximum=None):
    if type(x) not in (int,float) or not isfinite(x):
        raise ErroChuvaVazao(n+": número finito obrigatório")
    v=float(x)
    if minimum is not None and v<minimum or maximum is not None and v>maximum:
        raise ErroChuvaVazao(n+": fora do domínio validado")
    return v

def _ref(x,n):
    if not isinstance(x,str) or len(x.strip())<8 or len(x)>300:
        raise ErroChuvaVazao(n+": referência técnica obrigatória")
    return x

def _when(x):
    if not isinstance(x,str):
        raise ErroChuvaVazao("timestamp obrigatório")
    try:d=datetime.fromisoformat(x.replace("Z","+00:00"))
    except ValueError as exc:raise ErroChuvaVazao("timestamp inválido") from exc
    if d.tzinfo is None or d.utcoffset() is None:
        raise ErroChuvaVazao("timestamp exige fuso")
    return d.astimezone(timezone.utc)

def escoamento_scs_cn(*,chuva_evento_mm,numero_curva,
                     area_bacia_km2,fracao_abstracao_inicial,
                     fonte_cn,fonte_chuva):
    """S=25400/CN-254 mm; Ia=lambda*S; Q=(P-Ia)^2/(P+(1-lambda)S).

    lambda 0.2 é a hipótese clássica NRCS mas deve ser fornecida explicitamente.
    """
    p=_v(chuva_evento_mm,"chuva de evento",0,2000)
    cn=_v(numero_curva,"CN",30,100)
    area=_v(area_bacia_km2,"area da bacia",.000001,10_000_000)
    lam=_v(fracao_abstracao_inicial,"lambda",0,1)
    _ref(fonte_cn,"fonte de CN/solo/ocupação")
    _ref(fonte_chuva,"chuva por evento")
    s=25400/cn-254
    ia=lam*s
    if p<=ia:
        q=0.
    else:
        den=p+(1-lam)*s
        q=(p-ia)**2/den
    if q>p+1e-9 or q<0:
        raise ErroChuvaVazao("escoamento inconsistente com conservação de chuva")
    return {"precipitacao_evento_mm":p,"retencao_potencial_mm":s,
            "abstracao_inicial_mm":ia,"escoamento_direto_estimado_mm":q,
            "demais_perdas_estimadas_mm":max(0,p-q),
            "escoamento_evento_m3":q*area*1000,
            "fracao_escoamento":q/p if p else 0.,
            "cn":cn,"lambda":lam,
            "fonte_cn":fonte_cn,"fonte_chuva":fonte_chuva,
            "classificacao":"MODELO_EVENTO_SCS_CN_SEM_CALIBRACAO",
            "limites":"CN depende de solo, cobertura, manejo, umidade antecedente e evento. "
                      "Modelo de escoamento direto, não de descarga de rio sem propagação."}

def propagar_muskingum(*,serie_entrada,passo_horas,
                      tempo_viagem_k_h,peso_x,
                      vazao_saida_inicial_m3_s,fonte_calibracao):
    """O[t] = C0 I[t] + C1 I[t-1] + C2 O[t-1]; coeficientes >=0.

    Verifica conservação trapezoidal por trecho incluindo armazenamento.
    Ignora afluentes laterais e remanso; condições de contorno explícitas.
    """
    dt=_v(passo_horas,"passo horas",1/3600,240)
    k=_v(tempo_viagem_k_h,"K horas",1/3600,2400)
    x=_v(peso_x,"X",0,.5)
    o0=_v(vazao_saida_inicial_m3_s,"saída inicial",0,1e8)
    _ref(fonte_calibracao,"origem parâmetros K/X")
    if not isinstance(serie_entrada,(list,tuple)) or not 3<=len(serie_entrada)<=100000:
        raise ErroChuvaVazao("série de vazões com 3+ instantes obrigatória")
    if dt<2*k*x-1e-9 or dt>2*k*(1-x)+1e-9:
        raise ErroChuvaVazao("passo Muskingum instável: exigir 2 K X <= dt <= 2 K (1-X)")
    den=2*k*(1-x)+dt
    c0=(dt-2*k*x)/den
    c1=(dt+2*k*x)/den
    c2=(2*k*(1-x)-dt)/den
    coefs=[c0,c1,c2]
    if any(c<-1e-10 for c in coefs) or abs(sum(coefs)-1)>1e-9:
        raise ErroChuvaVazao("coeficientes Muskingum fora de estabilidade")
    t_prev=None;i_prev=None;o_prev=o0;history=[];max_error=0.
    s_prev=None
    for row in serie_entrada:
        if not isinstance(row,dict):
            raise ErroChuvaVazao("item do hidrograma inválido")
        t=_when(row.get("data_hora"))
        i=_v(row.get("vazao_entrada_m3_s"),"vazão entrada",0,1e8)
        if t_prev is not None:
            diff=(t-t_prev).total_seconds()/3600
            if abs(diff-dt)>1e-8:
                raise ErroChuvaVazao("lacuna, duplicata ou passo irregular")
            o=max(0,c0*i+c1*i_prev+c2*o_prev)
            s_new=k*3600*(x*i+(1-x)*o)
            fluxo=(i_prev+i-o_prev-o)/2*dt*3600
            error=(s_new-s_prev)-fluxo
            max_error=max(max_error,abs(error))
            if abs(error)>1e-7*max(1,abs(s_new),abs(s_prev),abs(fluxo)):
                raise ErroChuvaVazao("Muskingum não conserva volume discretizado")
        else:
            o=o0;s_new=k*3600*(x*i+(1-x)*o)
        history.append({"data_hora_utc":t.isoformat(),"entrada_m3_s":i,
                        "saida_modelada_m3_s":o,"volume_armazenado_modelado_m3":s_new})
        t_prev=t;i_prev=i;o_prev=o;s_prev=s_new
    return {"pontos":history,"coeficientes":{"C0":max(0,c0),"C1":max(0,c1),"C2":max(0,c2)},
            "max_erro_balanco_m3":max_error,
            "passo_horas":dt,"tempo_viagem_k_h":k,"peso_x":x,
            "fonte_calibracao":fonte_calibracao,
            "classificacao":"MUSKINGUM_LINEARMODEL_NAO_HOMOLOGADO",
            "limites":"Sem chuva lateral, infiltração no canal, remanso, "
                      "curva cota/vazão ou validação por trecho/estação. "
                      "Não atesta cheias nem navegabilidade."}
