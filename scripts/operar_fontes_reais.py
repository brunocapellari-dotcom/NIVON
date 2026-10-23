"""Execução integrada diária das fontes reais com persistência e export.

A nuvem só é acessada quando NIVON_BQ_EXECUTAR=1 e o ambiente tem ADC.
O status de cada fonte fica explícito; falha em uma fonte não apaga outras.
"""
from __future__ import annotations
import argparse
import json
import os
from datetime import date,datetime,timedelta,timezone
from pathlib import Path

from nivon.coletor_bcra_v4 import coletar_bcra
from nivon.coletor_granos_ar import coletar_granos_ar
from nivon.coletores_dados_reais import executar_coleta, descobrir_recurso_ccee_ano
from nivon.ingestao_fontes_reais import exportar_jsonl
from nivon.coletores_agro_ibge_wdi import coletar_ibge_pam, coletar_wdi

def safra_canadense(hoje):
    inicio=hoje.year if hoje.month>=8 else hoje.year-1
    return f"{inicio}-{(inicio+1)%100:02d}"

def operar(*,base="data/nivon",hoje=None,coletar_canada=False,coletar_ccee=False,
           coletar_ibge=False,coletar_banco_mundial=False,publicar_bigquery=False,
           projeto=None,dataset=None):
    hoje=date.today() if hoje is None else hoje
    if not isinstance(hoje,date):
        raise ValueError("hoje deve ser date")
    pasta=Path(base)
    pasta.mkdir(parents=True,exist_ok=True)
    db=pasta/"fontes_reais.sqlite"
    raw=pasta/"raw"
    start=(hoje-timedelta(days=14)).isoformat()
    fim=hoje.isoformat()
    jobs=[
        ("ARG_BCRA", lambda:coletar_bcra(inicio=start,fim=fim,banco=db,
                raw_dir=raw,executar=True)),
        ("ARG_GRANOS_AR_PIZARRA", lambda:coletar_granos_ar(endpoint="pizarra",
                banco=db,raw_dir=raw,executar=True)),
    ]
    if coletar_canada:
        jobs.append(("CAN_GRAINS_WEEKLY", lambda:executar_coleta(
            fonte="CAN_GRAINS_WEEKLY",banco=db,raw_dir=raw,
            safra=safra_canadense(hoje),executar=True)))
    if coletar_ccee:
        def _buscar_ccee():
            id_recurso=descobrir_recurso_ccee_ano(hoje.year)
            return executar_coleta(fonte="BR_CCEE_PLD",banco=db,raw_dir=raw,
                       recurso_id=id_recurso,executar=True)
        jobs.append(("BR_CCEE_PLD", _buscar_ccee))
    # Fontes anuais: não chamar de previsão de safra nem sinal intradiário.
    # Requests pontuais e explícitos, sem varrer todos os municípios.
    if coletar_ibge:
        for uf in ("MT","PR"):
            jobs.append((f"BR_IBGE_PAM_{uf}", lambda uf=uf:coletar_ibge_pam(
                ano=hoje.year-1,uf=uf,banco=db,raw_dir=raw,executar=True)))
    if coletar_banco_mundial:
        for country in ("BRA","ARG"):
            for metric in ("AG.YLD.CREL.KG","AG.CON.FERT.ZS"):
                jobs.append((f"WDI_{country}_{metric}",
                    lambda country=country,metric=metric:coletar_wdi(
                    pais=country,indicador=metric,inicio=hoje.year-7,
                    fim=hoje.year-1,banco=db,raw_dir=raw,executar=True)))
    respostas=[]
    for nome,fn in jobs:
        try:
            r=fn()
            respostas.append({"fonte":nome,"estado":"COLETADO",
                "observacoes_novas":r.get("novas_observacoes",0),
                "sha256":r.get("sha256")})
        except Exception as exc:
            respostas.append({"fonte":nome,"estado":"FALHOU",
              "erro":type(exc).__name__,"detalhe":str(exc)[:160]})
    exported=None
    bq=None
    if db.exists():
        exported=exportar_jsonl(banco=db,destino=pasta/"staging_fontes_reais.jsonl")
        if publicar_bigquery:
            if not projeto or not dataset:
                raise ValueError("projeto e dataset obrigatorios na carga BigQuery")
            if exported["observacoes"]==0:
                raise ValueError("sem observacoes nao enviar BigQuery")
            from nivon.carga_bigquery_fontes import executar_carga
            bq=executar_carga(arquivo=exported["arquivo"],project_id=projeto,
                             dataset_id=dataset,executar=True)
    sucesso=sum(r["estado"]=="COLETADO" for r in respostas)
    return {"fontes":respostas,"sucesso":sucesso,"falhas":len(respostas)-sucesso,
      "stage":exported,"bigquery":bq,"bigquery_executado":bool(bq),
      "estado":"PARCIAL" if sucesso<len(respostas) else "COLETAS_EXECUTADAS"}

def main(argv=None):
    p=argparse.ArgumentParser(description="NIVON: coleta de fontes operacionais")
    p.add_argument("--base",default="data/nivon")
    p.add_argument("--canada",action="store_true")
    p.add_argument("--ccee",action="store_true")
    p.add_argument("--ibge-pam",action="store_true")
    p.add_argument("--wdi",action="store_true")
    p.add_argument("--bigquery",action="store_true")
    p.add_argument("--projeto")
    p.add_argument("--dataset")
    p.add_argument("--relatorio")
    args=p.parse_args(argv)
    result=operar(base=args.base,coletar_canada=args.canada,
          coletar_ccee=args.ccee,
          coletar_ibge=args.ibge_pam,
          coletar_banco_mundial=args.wdi,
          publicar_bigquery=args.bigquery,projeto=args.projeto,dataset=args.dataset)
    output=json.dumps(result,ensure_ascii=False,indent=2)
    if args.relatorio:
        path=Path(args.relatorio)
        path.parent.mkdir(parents=True,exist_ok=True)
        path.write_text(output+"\n",encoding="utf-8")
    print(output)
    # Persistir RAW/analitico antes de avaliar falhas parciais.
    return 0 if result["sucesso"]>0 else 2

if __name__=="__main__":
    raise SystemExit(main())
