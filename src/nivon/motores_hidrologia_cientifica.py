"""NIVON: hidrologia quantitativa conservativa e curva-chave por estação.

Curva-chave interpolada entre aforos mensurados da MESMA época e datum.
Não ajusta rating curve automaticamente e proíbe extrapolação. Cota de
régua não é profundidade navegável. Balanço de reservatório em m3/dia.
"""
from __future__ import annotations
from math import exp, isfinite, log, sqrt

class ErroHidrologia(ValueError):
    pass

def _n(x,descricao,minimo=None,maximo=None):
    if type(x) not in (float,int) or not isfinite(x):
        raise ErroHidrologia(descricao+" inválido/não finito")
    val=float(x)
    if minimo is not None and val<minimo or maximo is not None and val>maximo:
        raise ErroHidrologia(descricao+" fora de limites")
    return val

def _id(x,nome):
    if not isinstance(x,str) or not 3<=len(x.strip())<=140:
        raise ErroHidrologia(nome+" obrigatório")
    return x

def curva_chave_interpolada(*,estacao_id,cota_cm,pares_aforos_cota_cm_vazao_m3s,
                           datum_referencia,versao_curva,fonte_aforos):
    """Interpolação log-linear de vazão positiva, sem extrapolação/certidão de vazão.

    Todos os aforos devem usar mesma referência vertical, estação e
    período de validade, previamente verificados pelo operador.
    """
    id=_id(estacao_id,"estação");_id(datum_referencia,"datum")
    _id(versao_curva,"versão");_id(fonte_aforos,"fonte aforos")
    cota=_n(cota_cm,"cota",-2000,20000)
    pairs=pares_aforos_cota_cm_vazao_m3s
    if not isinstance(pairs,(tuple,list)) or not 3<=len(pairs)<=10000:
        raise ErroHidrologia("exigir 3+ aforos reais da estação")
    dados=[]
    for pair in pairs:
        if not isinstance(pair,(tuple,list)) or len(pair)!=2:
            raise ErroHidrologia("aforo precisa ser cota e vazão")
        h=_n(pair[0],"cota aforo",-2000,20000)
        q=_n(pair[1],"vazão aforo",0.000001,1e7)
        dados.append((h,q))
    dados.sort()
    if any(h1<=h0 or q1<=q0 for (h0,q0),(h1,q1) in zip(dados,dados[1:])):
        raise ErroHidrologia("curva monótona estrita por cota e vazão")
    if not dados[0][0]<=cota<=dados[-1][0]:
        raise ErroHidrologia("extrapolação de curva-chave proibida")
    for h,q in dados:
        if cota==h:
            return _retorno_curva(id,cota,q,datum_referencia,versao_curva,
                                  fonte_aforos,(h,h),True)
    for (h0,q0),(h1,q1) in zip(dados,dados[1:]):
        if h0<cota<h1:
            fraction=(cota-h0)/(h1-h0)
            q=exp(log(q0)+fraction*(log(q1)-log(q0)))
            return _retorno_curva(id,cota,q,datum_referencia,versao_curva,
                                  fonte_aforos,(h0,h1),False)
    raise ErroHidrologia("nenhum intervalo de aforo")

def _retorno_curva(estacao,cota,q,datum,versao,fonte,intervalo,exato):
    return {"estacao_id":estacao,"cota_cm":cota,
            "vazao_interpolada_m3_s":q,"intervalo_aforos_cm":intervalo,
            "aforo_exato":exato,"datum":datum,"versao_curva":versao,
            "fonte_aforos":fonte,
            "classificacao":"INTERPOLACAO_CURVA_CHAVE_NAO_MEDICAO",
            "limite":"Relação cota-vazão muda com leito, cheias e remanso. "
                     "Não usar fora da época/datum dos aforos; não é calado navegável."}

def balanco_reservatorio_diario(*,volume_inicial_m3,volume_maximo_m3,
                               entrada_m3_s,saida_m3_s,
                               precipitacao_mm,evaporacao_mm,
                               area_lamina_km2,duracao_segundos,
                               fonte_metrica):
    """Contabilidade volumes, não otimização operacional ou hidrograma."""
    vi=_n(volume_inicial_m3,"volume inicial",0,1e15)
    vmax=_n(volume_maximo_m3,"capacidade",1,1e15)
    if vi>vmax:raise ErroHidrologia("armazenamento excede capacidade")
    qi=_n(entrada_m3_s,"inflow",0,1e9)
    qo=_n(saida_m3_s,"outflow",0,1e9)
    p=_n(precipitacao_mm,"chuva",0,2000)
    evap=_n(evaporacao_mm,"evaporação",0,100)
    area=_n(area_lamina_km2,"área",0,1e7)
    dur=_n(duracao_segundos,"duração segundos",1,86400)
    _id(fonte_metrica,"fonte")
    # 1 mm * 1 km2 = 1000 m3
    entrada=qi*dur+p*area*1000
    retirada=qo*dur+evap*area*1000
    bruto=vi+entrada-retirada
    if bruto < -1e-6:
        raise ErroHidrologia("retirada excede volume disponível na hipótese")
    vertimento=max(0,bruto-vmax)
    vf=min(vmax,max(0,bruto))
    if abs((vi+entrada)-(retirada+vertimento+vf))>1e-5*max(1.,vi+entrada):
        raise ErroHidrologia("não fecha conservação volumétrica")
    return {"volume_final_m3":vf,"aporte_total_m3":entrada,
            "retirada_declarada_m3":retirada,"vertimento_teorico_m3":vertimento,
            "balanco_bruto_m3":bruto,
            "fonte":fonte_metrica,
            "classificacao":"BALANCO_RESERVATORIO_DETERMINISTICO",
            "limite":"Área de lâmina fixa, sem infiltração/captação lateral, "
                     "curva cota-área-volume ou operação real. Vertimento teórico não é descarga observada."}

def avaliar_previsao_vazao(*,observado_m3s,previsto_m3s,
                          baseline_persistencia_m3s,
                          fonte_observado,fonte_previsao):
    """NSE, MAE, RMSE, viés e melhoria contra persistência com série alinhada.

    Passar somente vintages PREVISTOS antes dos respectivos dias válidos.
    O motor NÃO demonstra que essa condição foi verificada externamente.
    """
    obs=observado_m3s;prev=previsto_m3s;base=baseline_persistencia_m3s
    if not all(isinstance(v,(list,tuple)) for v in (obs,prev,base)):
        raise ErroHidrologia("séries alinhadas obrigatórias")
    if not 10<=len(obs)<=100000 or len(prev)!=len(obs) or len(base)!=len(obs):
        raise ErroHidrologia("amostra insuficiente, vazios ou horizontes desalinhados")
    _id(fonte_observado,"observado");_id(fonte_previsao,"previsão")
    obs=[_n(x,"vazão observada",0) for x in obs]
    prev=[_n(x,"vazão prevista",0) for x in prev]
    base=[_n(x,"persistência",0) for x in base]
    n=len(obs);average=sum(obs)/n
    variance=sum((o-average)**2 for o in obs)
    err=[p-o for p,o in zip(prev,obs)]
    se=sum(x*x for x in err)
    se_baseline=sum((p-o)**2 for p,o in zip(base,obs))
    mae=sum(abs(x) for x in err)/n
    rmse=sqrt(se/n)
    bias=sum(err)/n
    return {"n":n,"mae_m3_s":mae,"rmse_m3_s":rmse,"bias_m3_s":bias,
            "nse":1-se/variance if variance>0 else None,
            "rmse_persistencia_m3_s":sqrt(se_baseline/n),
            "skill_mse_contra_persistencia":1-se/se_baseline if se_baseline>0 else None,
            "fonte_observado":fonte_observado,"fonte_previsao":fonte_previsao,
            "classificacao":"METRICAS_RETROSPECTIVAS_NAO_HOMOLOGA_FORECAST",
            "limite":"Requer pareamento por estação/data/lead-time e publicação "
                     "anterior à previsão; somente backtesting walk-forward prova desempenho."}
