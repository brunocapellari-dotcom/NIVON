"""Séries mensais dos polos ferroviários a partir de staging SIADE auditado.

Usa montar_lote para revalidar CSV + SHA e manifesto; nunca infere transbordo.
"""
from __future__ import annotations
import argparse
from collections import defaultdict
from decimal import Decimal
import json
from pathlib import Path
import re
import sys
from .antt_bigquery import montar_lote
from .conciliacao_corredores_ferrovia import _produto, _decimal, _polo_estacao, ErroConciliacao


def serie_staging(pasta, anos, *, uf_origem="MT", max_rank=10):
    if (not isinstance(anos,list) or not anos or len(anos)>30 or
        any(type(a) is not int or not 2006<=a<=2100 for a in anos) or len(set(anos))!=len(anos)):
        raise ErroConciliacao("lista de anos inválida")
    if not isinstance(uf_origem,str) or not re.fullmatch(r"[A-Z]{2}",uf_origem):
        raise ErroConciliacao("UF de origem inválida")
    if type(max_rank) is not int or not 1<=max_rank<=100:
        raise ErroConciliacao("limite inválido")

    grupos=defaultdict(lambda:Decimal(0))
    rotas=defaultdict(lambda:Decimal(0))
    mercadorias=defaultdict(lambda:Decimal(0))
    evidencias=[]
    linhas_por_polo=defaultdict(int)
    for ano in sorted(anos):
        rows,meta=montar_lote(pasta,ano)
        if meta["registros"]!=len(rows):
            raise ErroConciliacao("lote divergente")
        evidencias.append({
            "ano":ano,"arquivo_sha256":meta["sha256"],
            "registros_total_arquivo":meta["registros"],
            "ultima_competencia_publicada":meta["competencia_maxima"],
            "classificacao":"ANTT_SIADE_PARSEADO_NAO_HOMOLOGADO"})
        vistos=set()
        for row in rows:
            comp=row["competencia"]
            if not re.fullmatch(r"20\d\d-(0[1-9]|1[0-2])",comp) or int(comp[:4])!=ano:
                raise ErroConciliacao("competência divergente")
            if row["uf_origem"]!=uf_origem:
                continue
            if row["linha_id"] in vistos:
                raise ErroConciliacao("registro ferroviário repetido")
            vistos.add(row["linha_id"])
            t=_decimal(row["toneladas_uteis"])
            for polo in _polo_estacao(row["estacao_origem"],uf_origem):
                pid=polo["id"]
                prod=_produto(row["mercadoria"]) or "SEM_CLASSIFICACAO"
                grupos[(comp,pid,prod)]+=t
                mercadorias[(comp,pid,row["mercadoria"])]+=t
                rotas[(comp,pid,prod,row["estacao_destino"],row["uf_destino"])]+=t
                linhas_por_polo[(comp,pid)]+=1

    totais=defaultdict(lambda:Decimal(0))
    for (comp,polo,produto),valor in grupos.items():
        totais[(comp,polo)]+=valor
    serie=[]
    for (comp,polo),tu in sorted(totais.items()):
        evid=next(e for e in evidencias if e["ano"]==int(comp[:4]))
        dest=sorted(((destino,uf,prod,v) for (mes,pid,prod,destino,uf),v in rotas.items()
                     if mes==comp and pid==polo),
                    key=lambda x:(-x[3],x[0],x[1],x[2]))
        serie.append({
            "polo_id":polo,"competencia":comp,"data_referencia":comp+"-01",
            "toneladas_uteis":format(tu,"f"),"linhas_od":linhas_por_polo[(comp,polo)],
            "mercadorias_fonte":[{"mercadoria_antt":m,"toneladas_uteis":format(v,"f")}
                for (mes,pid,m),v in sorted(mercadorias.items())
                if mes==comp and pid==polo],
            "produtos":[{"produto_normalizado":prod,"toneladas_uteis":format(v,"f")}
                for (mes,pid,prod),v in sorted(grupos.items())
                if mes==comp and pid==polo],
            "principais_destinos":[{"estacao_destino":d,"uf_destino":uf,
                "produto_normalizado":pr,"toneladas_uteis":format(v,"f")}
                for d,uf,pr,v in dest[:max_rank]],
            "destinos_truncados":len(dest)>max_rank,
            "arquivo_sha256":evid["arquivo_sha256"],
            "fonte":"ANTT_SIADE_ORIGEM_DESTINO",
            "classificacao":"TU_DECLARADA_MATCH_NOME_ESTACAO",
            "terminal_confirmado":False,"transbordo_confirmado":False,
        })
    indice={(r["competencia"],r["polo_id"]):r for r in serie}
    for item in serie:
        ano=int(item["competencia"][:4])
        anterior=indice.get((f"{ano-1}{item['competencia'][4:]}",item["polo_id"]))
        if anterior is None:
            item["comparacao_yoy"]="MES_ANTERIOR_AUSENTE_NAO_ZERO"
            item["variacao_yoy_pct"]=None
            continue
        base=Decimal(anterior["toneladas_uteis"])
        atual=Decimal(item["toneladas_uteis"])
        item["comparacao_yoy"]="BASE_ZERO_SEM_PERCENTUAL" if base==0 else "COMPARAVEL_MES_EQUIVALENTE"
        item["variacao_yoy_pct"]=(format(((atual-base)/base*100).quantize(Decimal("0.01")),"f")
                                  if base else None)
    return {
        "estado":"SERIE_FERROVIARIA_NAO_CONCILIADA_TERMINAL",
        "fonte":"ANTT_SIADE_ORIGEM_DESTINO",
        "abrangencia":"FERROVIAS_FEDERAIS_CONCEDIDAS","uf_origem":uf_origem,
        "anos":sorted(anos),"evidencias":evidencias,
        "polos_meses_com_registro":len(serie),
        "competencias_distintas":sorted({r["competencia"] for r in serie}),
        "serie":serie,
        "regra":"Sem linha SIADE para polo não significa volume zero; sem soma com MDF-e/ANTAQ.",
    }


def main(argv=None):
    p=argparse.ArgumentParser(description="Série mensal polos SIADE por estação de origem")
    p.add_argument("--staging",required=True)
    p.add_argument("--anos",type=int,nargs="+",required=True)
    p.add_argument("--uf-origem",default="MT")
    p.add_argument("--output",required=True)
    args=p.parse_args(argv)
    try:
        doc=serie_staging(args.staging,args.anos,uf_origem=args.uf_origem)
        target=Path(args.output)
        target.parent.mkdir(parents=True,exist_ok=True)
        target.write_text(json.dumps(doc,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
        print(json.dumps({"estado":doc["estado"],"linhas":len(doc["serie"]),
                          "evidencias":doc["evidencias"]},ensure_ascii=False))
        return 0
    except (ErroConciliacao,OSError,ValueError,KeyError) as exc:
        print(json.dumps({"estado":"FALHA_FONTE_SERIE","tipo":type(exc).__name__}),file=sys.stderr)
        return 2

if __name__=="__main__":
    raise SystemExit(main())
