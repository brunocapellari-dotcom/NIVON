"""Tendências DESCRITIVAS de comércio exterior, YoY no mesmo mês.
Não é previsão de preços, portos, fretes ou movimentos efetivos.
"""
from __future__ import annotations

from datetime import datetime
from math import isfinite
from statistics import median

class ErroTendenciaMDIC(ValueError):
    pass

def classificar_tendencia_mdic(serie_preparada:dict,*,limiar_pct:float=5.0,
                              consenso_minimo:float=0.75,
                              permitir_sinteticos_para_teste:bool=False)->dict:
    if (not isinstance(serie_preparada,dict)
        or serie_preparada.get("classe")!="SERIE_EXPLORATORIA_SEM_HOMOLOGACAO"
        or serie_preparada.get("apta_publicacao_preditiva") is not False):
        raise ErroTendenciaMDIC("série não aprovada pelo contrato canônico")
    if serie_preparada.get("somente_dados_reais") is not True and permitir_sinteticos_para_teste is not True:
        raise PermissionError("série sintética requer opt-in de teste")
    if (type(limiar_pct) not in (int,float) or not isfinite(limiar_pct)
        or not 0.1<=limiar_pct<=50):
        raise ErroTendenciaMDIC("limiar inválido")
    if (type(consenso_minimo) not in (int,float)
        or not isfinite(consenso_minimo) or not 0.5<consenso_minimo<=1):
        raise ErroTendenciaMDIC("consenso inválido")
    serie=serie_preparada.get("serie")
    if not isinstance(serie,list) or not 24<=len(serie)<=120:
        raise ErroTendenciaMDIC("menos de 24 meses ou série muito longa")
    esperado=None
    for item in serie:
        if not isinstance(item,(list,tuple)) or len(item)!=2 or not isinstance(item[0],str):
            raise ErroTendenciaMDIC("observação inválida")
        try: d=datetime.strptime(item[0],"%Y-%m")
        except ValueError as exc:raise ErroTendenciaMDIC("competência inválida") from exc
        if item[0]!=d.strftime("%Y-%m") or (esperado is not None and d.year*12+d.month!=esperado):
            raise ErroTendenciaMDIC("competência duplicada ou descontínua")
        esperado=d.year*12+d.month+1
        valor=item[1]
        if type(valor) not in (float,int) or not isfinite(valor) or valor<0:
            raise ErroTendenciaMDIC("valor ausente ou não físico")
    taxas=[]
    ausentes=[]
    for i in range(len(serie)-12,len(serie)):
        base=float(serie[i-12][1])
        atual=float(serie[i][1])
        if base==0:
            ausentes.append(serie[i][0])
        else:
            taxas.append(100*(atual/base-1))
    med=median(taxas) if taxas else None
    mad=median(abs(x-med) for x in taxas) if taxas else None
    classe="INDETERMINADA"
    acordo=0.0
    if len(taxas)==12:
        altas=sum(x>limiar_pct for x in taxas)/12
        baixas=sum(x<-limiar_pct for x in taxas)/12
        estaveis=sum(abs(x)<=limiar_pct for x in taxas)/12
        acordo=max(altas,baixas,estaveis)
        if med>limiar_pct and altas>=consenso_minimo:
            classe="ALTA"
        elif med<-limiar_pct and baixas>=consenso_minimo:
            classe="BAIXA"
        elif abs(med)<=limiar_pct and estaveis>=consenso_minimo:
            classe="ESTABILIDADE"
    return {
        "tendencia":classe,"mediana_yoy_pct":med,"dispersao_mad_pp":mad,
        "meses_validos":len(taxas),"sem_denominador":ausentes,
        "concordancia":acordo,"limiar_pct":float(limiar_pct),
        "consenso_minimo":float(consenso_minimo),"ultimo_mes":serie[-1][0],
        "dataset_id":serie_preparada["dataset_id"],
        "produto":serie_preparada["codigo_produto"],
        "uf":serie_preparada["uf_fiscal_ou_ncm"],
        "variavel":serie_preparada["variavel"],
        "unidade":serie_preparada["unidade"],
        "vintages":serie_preparada["vintages"],
        "metodo":"COMPARACAO_MENSAL_MESMO_MES_ANO_ANTERIOR",
        "probabilidade_de_movimento_futuro":None,
        "fluxo_fisico_ou_frete_inferido":False,
        "homologado":False,"publicavel":False,
    }
