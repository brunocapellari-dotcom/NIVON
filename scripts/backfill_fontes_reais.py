"""Backfill segmentado de séries CCEE e Canadá — sem agregações inventadas.

Usa exatamente o mesmo parser e dedupe da coleta corrente, ano a ano.
Não agenda operações nem grava nuvem; armazenamento permanente segue
pelo fluxo GCS -> BigQuery após credenciais e licenças verificadas.
"""
from __future__ import annotations

import argparse
import json
from datetime import date
from pathlib import Path
from nivon.coletores_dados_reais import executar_coleta, descobrir_recurso_ccee_ano


class ErroBackfill(ValueError):
    pass


def planejar_historico(*, fonte, inicio, fim, max_anos=10):
    if fonte not in ("BR_CCEE_PLD", "CAN_GRAINS_WEEKLY"):
        raise ErroBackfill("fonte sem historico segmentado")
    if type(inicio) is not int or type(fim) is not int or type(max_anos) is not int:
        raise ErroBackfill("anos devem ser inteiros")
    menor = 2021 if fonte=="BR_CCEE_PLD" else 2000
    if not menor<=inicio<=fim<=date.today().year or not 1<=fim-inicio+1<=max_anos<=20:
        raise ErroBackfill("janela historica acima do limite")
    return [{"fonte":fonte,"ano":ano,
             "safra":f"{ano}-{(ano+1)%100:02d}" if fonte=="CAN_GRAINS_WEEKLY" else None}
            for ano in range(inicio,fim+1)]


def backfill(*, fonte, inicio, fim, banco, raw_dir, executar=False,
             cliente=None, max_anos=10):
    plano=planejar_historico(fonte=fonte,inicio=inicio,fim=fim,max_anos=max_anos)
    if executar is not True:
        return {"fonte":fonte,"plano":plano,"executado":False}
    resultados=[]
    for item in plano:
        try:
            if fonte=="BR_CCEE_PLD":
                uuid=descobrir_recurso_ccee_ano(item["ano"],cliente=cliente)
                res=executar_coleta(fonte=fonte,executar=True,
                      banco=banco,raw_dir=raw_dir,recurso_id=uuid,cliente=cliente)
            else:
                res=executar_coleta(fonte=fonte,executar=True,
                      banco=banco,raw_dir=raw_dir,safra=item["safra"],cliente=cliente)
            resultados.append({"ano":item["ano"],"estado":"RECEBIDO",
                   "novas_observacoes":res["novas_observacoes"],
                   "snapshot_id":res["snapshot_id"]})
        except Exception as exc:
            # Uma fonte pode não publicar alguma edição; não criar observação 0.
            resultados.append({"ano":item["ano"],"estado":"FALHOU",
                "erro":type(exc).__name__,"detalhe":str(exc)[:140]})
    return {"fonte":fonte,"executado":True,"lotes":resultados,
        "lotes_com_sucesso":sum(x["estado"]=="RECEBIDO" for x in resultados),
        "falhas":sum(x["estado"]=="FALHOU" for x in resultados),
        "persistencia":"SQLITE_LOCAL_RAW_NAO_CLOUD"}


def main(argv=None):
    p=argparse.ArgumentParser(description="NIVON: backfill oficial por ano")
    p.add_argument("--fonte",required=True,choices=("BR_CCEE_PLD","CAN_GRAINS_WEEKLY"))
    p.add_argument("--inicio",type=int,required=True)
    p.add_argument("--fim",type=int,required=True)
    p.add_argument("--max-anos",type=int,default=10)
    p.add_argument("--banco",default="data/nivon/fontes_reais.sqlite")
    p.add_argument("--raw-dir",default="data/nivon/raw")
    p.add_argument("--executar",action="store_true")
    a=p.parse_args(argv)
    out=backfill(fonte=a.fonte,inicio=a.inicio,fim=a.fim,
       banco=a.banco,raw_dir=a.raw_dir,max_anos=a.max_anos,executar=a.executar)
    print(json.dumps(out,ensure_ascii=False,indent=2))
    return 0 if not a.executar or out["falhas"]==0 else 2


if __name__=="__main__":
    raise SystemExit(main())
