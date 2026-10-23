"""Backfill histórico -> RAW GCS -> BigQuery, por ano e com gates de custo.

Execução manual isolada; não dispara automaticamente. Falhas de anos são
registradas e não impedem arquivamento dos dados reais já coletados.
"""
from __future__ import annotations

import argparse
import json
import tempfile
from pathlib import Path

from nivon.arquivo_raw_gcs import arquivar_gcs
from nivon.lote_cloud_recuperavel import arquivar_stage
from nivon.carga_bigquery_fontes import executar_carga
from nivon.ingestao_fontes_reais import exportar_jsonl
from nivon.preflight_gcp_fontes import verificar_nuvem
from scripts.backfill_fontes_reais import backfill, planejar_historico


def executar_historico(*, fonte, inicio, fim, projeto, dataset, bucket,
                       executar=False, max_anos=5,
                       arquivar_recuperacao=False):
    plano=planejar_historico(fonte=fonte,inicio=inicio,fim=fim,max_anos=max_anos)
    if executar is not True:
        return {"fonte":fonte,"anos":plano,"modo":"SIMULACAO_SEM_REDE"}
    preflight=verificar_nuvem(projeto=projeto,dataset=dataset,bucket=bucket)
    dataset_id=("BR_CCEE_PLD_HORARIO" if fonte=="BR_CCEE_PLD"
                else "CAN_GRAINS_CROP_YEAR_WEEKLY")
    with tempfile.TemporaryDirectory(prefix="nivon-historico-") as tmp:
        root=Path(tmp)
        result=backfill(fonte=fonte,inicio=inicio,fim=fim,
                        banco=root/"historico.sqlite",raw_dir=root/"raw",
                        executar=True,max_anos=max_anos)
        recebidos=[r for r in result["lotes"] if r["estado"]=="RECEBIDO"]
        if not recebidos:
            return {"estado":"SEM_LOTES_VALIDOS","falhas":result["falhas"],
                    "bigquery_executado":False}
        arquivo=arquivar_gcs(banco=root/"historico.sqlite",
                 raw_dir=root/"raw",bucket=bucket,executar=True)
        carregados=[]
        for info in recebidos:
            ano=info["ano"]
            destino=root/f"{dataset_id}_{ano}.jsonl"
            parametros={"competencia":f"{ano}-{ano+1}"} if fonte=="CAN_GRAINS_WEEKLY" else {
                "referencia_inicio":f"{ano}-01-01","referencia_fim":f"{ano}-12-31"}
            saida=exportar_jsonl(banco=root/"historico.sqlite",destino=destino,
                      dataset_id=dataset_id,**parametros)
            if saida["observacoes"]==0:
                carregados.append({"ano":ano,"estado":"SEM_DADOS_NORMALIZADOS"})
                continue
            # Arquivo completo do lote no GCS ANTES do BigQuery. Se o MERGE
            # falhar, replay pelo manifesto funciona sem rerodar HTTP/backfill.
            recibo=None
            if arquivar_recuperacao:
                recibo=arquivar_stage(
                    banco=root/"historico.sqlite",arquivo_jsonl=saida["arquivo"],
                    bucket=bucket,projeto=projeto,dataset=dataset,executar=True)
            carga=executar_carga(arquivo=saida["arquivo"],project_id=projeto,
                       dataset_id=dataset,executar=True)
            carregados.append({"ano":ano,"estado":"CARREGADO",
                         "observacoes":saida["observacoes"],
                         "linhas_enviadas":carga["linhas_enviadas"],
                         "manifesto_sha256":recibo["manifesto_sha256"] if recibo else None})
        return {"fonte":fonte,"estado":"PARCIAL" if result["falhas"] else "CONCLUIDO",
          "anos":result["lotes"],"arquivamento":arquivo,
          "cargas_bigquery":carregados,"falhas":result["falhas"],
          "cloud_preflight":bool(preflight["tabela_validada"])}


def main(argv=None):
    p=argparse.ArgumentParser(description="Backfill NIVON para GCS e BigQuery")
    p.add_argument("--fonte",required=True,choices=["BR_CCEE_PLD","CAN_GRAINS_WEEKLY"])
    p.add_argument("--inicio",type=int,required=True)
    p.add_argument("--fim",type=int,required=True)
    p.add_argument("--projeto",required=True)
    p.add_argument("--dataset",required=True)
    p.add_argument("--bucket",required=True)
    p.add_argument("--executar",action="store_true")
    p.add_argument("--arquivar-recuperacao",action="store_true")
    args=p.parse_args(argv)
    ret=executar_historico(fonte=args.fonte,inicio=args.inicio,fim=args.fim,
      projeto=args.projeto,dataset=args.dataset,bucket=args.bucket,
      executar=args.executar,
      arquivar_recuperacao=args.arquivar_recuperacao)
    print(json.dumps(ret,ensure_ascii=False,indent=2))
    return 2 if ret.get("falhas") else 0

if __name__=="__main__":
    raise SystemExit(main())
