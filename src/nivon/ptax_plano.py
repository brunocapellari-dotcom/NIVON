"""Planejador offline da API PTAX/OData, sem rede ou agendamento.

Janelas pequenas e determinísticas, USD/EUR separados, boletins completos:
não presume que uma cotação qualquer é fechamento.
"""
from __future__ import annotations
from datetime import date, timedelta
from urllib.parse import urlencode

BASE = "https://olinda.bcb.gov.br/olinda/servico/PTAX/versao/v1/odata/"

class ErroPlanoPTAX(ValueError):
    pass

def _data(valor, nome):
    if not isinstance(valor,str) or len(valor)!=10:
        raise ErroPlanoPTAX(f"{nome}: data AAAA-MM-DD obrigatória")
    try:
        d=date.fromisoformat(valor)
    except ValueError as exc:
        raise ErroPlanoPTAX(f"{nome}: data inválida") from exc
    if d.isoformat()!=valor:
        raise ErroPlanoPTAX(f"{nome}: data não canônica")
    return d

def planejar_consultas_ptax(*,moeda:str,inicio:str,fim:str,dias_janela:int=20)->list[dict]:
    if moeda not in ("USD","EUR"):
        raise ErroPlanoPTAX("moeda diferente de USD/EUR")
    a,b=_data(inicio,"inicio"),_data(fim,"fim")
    if a>b or (b-a).days+1>366:
        raise ErroPlanoPTAX("lote maior que 366 dias ou invertido")
    if type(dias_janela) is not int or not 1<=dias_janela<=20:
        raise ErroPlanoPTAX("janelas entre 1 e 20 dias")
    if moeda=="USD":
        endpoint="CotacaoDolarPeriodo(dataInicial=@dataInicial,dataFinalCotacao=@dataFinalCotacao)"
        moeda_param={}
    else:
        endpoint="CotacaoMoedaPeriodo(moeda=@moeda,dataInicial=@dataInicial,dataFinalCotacao=@dataFinalCotacao)"
        moeda_param={"@moeda":"'EUR'"}
    saida=[]
    cursor=a
    while cursor<=b:
        final=min(cursor+timedelta(days=dias_janela-1),b)
        params={**moeda_param,"@dataInicial":f"'{cursor:%m-%d-%Y}'",
                "@dataFinalCotacao":f"'{final:%m-%d-%Y}'",
                "$format":"json","$top":"500"}
        saida.append({
            "dataset_id":"BCB_PTAX","moeda":moeda,
            "inicio":cursor.isoformat(),"fim":final.isoformat(),
            "url":BASE+endpoint+"?"+urlencode(params),
            "estado":"PLANEJADO_OFFLINE_SEM_COLETA",
            "semantica":"BOLETINS_DIARIOS_NAO_FECHAMENTO",
        })
        cursor=final+timedelta(days=1)
    return saida
