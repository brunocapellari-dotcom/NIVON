"""Reprocessar um lote marítimo arquivado no GCS após falha do BigQuery.

Nao volta a consultar websites; verifica SHA-256 de cada evidencia,
reconstrói staging efêmero e regrava BigQuery por MERGE idempotente.
"""
from __future__ import annotations

import argparse
import json
import tempfile
from pathlib import Path

from nivon.maritimo_cloud_storage import ArquivoMaritimoGCS
from nivon.maritimo_pipeline import HistoricoMaritimo, processar_html, HTML_AUTORIZADO
from nivon.maritimo_lote import _registrar, preparar_registro
from nivon.maritimo_bigquery import sincronizar_bigquery
from nivon.portwatch_fluxos import HistoricoPortWatch, normalizar, PASSAGENS


def reprocessar_manifesto(*, bucket, uri, projeto, dataset="nivon_maritimo",
                          storage_client=None, bigquery_client=None,
                          bigquery_module=None, dry_run=False):
    archive=ArquivoMaritimoGCS(bucket,storage_client=storage_client)
    manifest=archive.ler_manifesto(uri)
    ledger={r["fonte"]:r for r in manifest["execucoes"]}
    with tempfile.TemporaryDirectory(prefix="nivon-replay-") as tmp:
        port=Path(tmp)/"portos.sqlite"
        pw=Path(tmp)/"portwatch.sqlite"
        history=HistoricoMaritimo(port)
        reconstructed=0
        pending_pw=[]
        try:
            preparar_registro(history)
            for item in manifest["snapshots"]:
                source=item["fonte"]
                previous=ledger.get(source if source!="fmi_portwatch" else "FMI_PORTWATCH")
                if not previous or previous["estado"]=="FALHA":
                    continue
                raw=archive.ler_evidencia(item)
                if source in HTML_AUTORIZADO:
                    result=processar_html(source,raw.decode("utf-8"),history,
                                           coletado_em=item["coletado_em"])
                    if previous["estado"]=="OK" and result["qualidade"]["quarentena"]:
                        raise ValueError("parser alterou estado OK anterior; exige reconciliacao")
                    reconstructed+=1
                elif source=="fmi_portwatch":
                    if manifest.get("portwatch_estado")=="OK":
                        rows,_=normalizar(raw,consultadas=tuple(PASSAGENS),
                                         coletado_em=item["coletado_em"])
                        pending_pw.extend(rows)
                else:
                    raise ValueError("fonte de manifesto nao autorizada")
            if pending_pw:
                store=HistoricoPortWatch(pw)
                try:
                    store.inserir(pending_pw)
                finally:
                    store.fechar()
            for entry in manifest["execucoes"]:
                _registrar(history,entry)
        finally:
            history.fechar()
        synced=sincronizar_bigquery(
            port,portwatch_banco=pw if pw.is_file() else None,
            projeto=projeto,dataset=dataset,client=bigquery_client,
            bigquery_module=bigquery_module,dry_run=dry_run)
        return {"run_id":manifest["run_id"],"fontes_reprocessadas":reconstructed,
                "linhas_portwatch":len(pending_pw),
                "bigquery":synced}


def main(argv=None):
    p=argparse.ArgumentParser(description="NIVON GCS -> BigQuery replay imutavel")
    p.add_argument("--bucket",required=True)
    p.add_argument("--manifesto",required=True)
    p.add_argument("--projeto",required=True)
    p.add_argument("--dataset",default="nivon_maritimo")
    p.add_argument("--dry-run",action="store_true")
    opt=p.parse_args(argv)
    result=reprocessar_manifesto(bucket=opt.bucket,uri=opt.manifesto,projeto=opt.projeto,
                                 dataset=opt.dataset,dry_run=opt.dry_run)
    # Retorno curto: nenhum dado de terceiros exposto no stdout
    print(json.dumps(result,ensure_ascii=False,sort_keys=True))


if __name__=="__main__":
    main()
