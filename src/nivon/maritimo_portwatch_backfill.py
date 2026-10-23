"""Retrocarga limitada e retomável do FMI PortWatch no Google Cloud.

Não dispara navegação histórica sem gate explícito, nem tenta baixar
todos os dados em uma única consulta. Cada janela gera manifesto GCS
ANTES do MERGE BigQuery, podendo ser reprocessada isoladamente.
"""
from __future__ import annotations

import argparse
import json
import os
import tempfile
from datetime import date,datetime,timedelta,timezone
from pathlib import Path

from nivon.maritimo_pipeline import HistoricoMaritimo
from nivon.maritimo_lote import executar_portwatch
from nivon.maritimo_cloud_storage import ArquivoMaritimoGCS
from nivon.maritimo_bigquery import sincronizar_bigquery,validar_destino

PASSAGENS=("hormuz","bab_el_mandeb","suez","panama")
MAX_JANELAS=4


def janelas(inicio,fim,*,limite=MAX_JANELAS):
    start=date.fromisoformat(inicio)
    end=date.fromisoformat(fim)
    if start<date(2019,1,1) or end<start:
        raise ValueError("periodo fora da disponibilidade prevista do PortWatch")
    if not 1<=limite<=MAX_JANELAS:
        raise ValueError("limite de janelas invalido")
    out=[]
    while start<=end:
        if len(out)>=limite:
            raise ValueError("periodo excede limite de janelas; dividir a retrocarga")
        stop=min(start+timedelta(days=30),end)
        out.append((start.isoformat(),stop.isoformat()))
        start=stop+timedelta(days=1)
    return out


def retrocarregar(*, inicio, fim, projeto, bucket, dataset="nivon_maritimo",
                 env=None, storage_client=None, bigquery_client=None,
                 bigquery_module=None, fornecer_pagina=None, dry_run=False):
    variables=os.environ if env is None else env
    if variables.get("NIVON_PORTWATCH_BACKFILL_HABILITADO")!="true":
        raise PermissionError("retrocarga desabilitada")
    validar_destino(projeto,dataset)
    spans=janelas(inicio,fim)
    archive=ArquivoMaritimoGCS(bucket,storage_client=storage_client)
    resultados=[]
    for begin,end in spans:
        with tempfile.TemporaryDirectory(prefix="nivon-backfill-") as folder:
            db_path=Path(folder)/"linha.sqlite"
            pw_path=Path(folder)/"fluxo.sqlite"
            stage=HistoricoMaritimo(db_path)
            objects=[]
            try:
                def on_page(url,payload,offset):
                    when=datetime.now(timezone.utc).isoformat()
                    out=archive.arquivar("fmi_portwatch",payload,coletado_em=when)
                    objects.append(dict(fonte="fmi_portwatch",coletado_em=when,**out))
                status=executar_portwatch(PASSAGENS,begin,end,
                    banco_lineups=stage,banco_portwatch=pw_path,
                    fornecer_json=fornecer_pagina,
                    permitir_rede=fornecer_pagina is None,
                    archivador_pagina=on_page)
            finally:
                stage.fechar()
            # Mesmo uma falha recebe manifesto/estado rastreavel no Storage.
            manifest=archive.gravar_manifesto(
                run_id=status["run_id"],snapshots=objects,
                execucoes=[status],portwatch_estado=status["estado"])
            persisted=sincronizar_bigquery(db_path,
                portwatch_banco=pw_path if pw_path.is_file() else None,
                projeto=projeto,dataset=dataset,client=bigquery_client,
                bigquery_module=bigquery_module,dry_run=dry_run)
            resultados.append(dict(inicio=begin,fim=end,estado=status["estado"],
                registros=status["quantidade"],manifesto=manifest,
                gravado=persisted["gravado"]))
            if status["estado"]!="OK":
                # Lote falho nao cancela evidencias; evita chamadas extras ao provedor.
                raise RuntimeError("retrocarga interrompida; conferir manifesto GCS do ultimo intervalo")
    return resultados


def main(argv=None):
    p=argparse.ArgumentParser(description="Retrocarga FMI PortWatch -> GCS -> BigQuery")
    p.add_argument("--inicio",required=True)
    p.add_argument("--fim",required=True)
    p.add_argument("--projeto",required=True)
    p.add_argument("--bucket",required=True)
    p.add_argument("--dataset",default="nivon_maritimo")
    p.add_argument("--dry-run",action="store_true")
    opt=p.parse_args(argv)
    out=retrocarregar(inicio=opt.inicio,fim=opt.fim,projeto=opt.projeto,
                    dataset=opt.dataset,bucket=opt.bucket,dry_run=opt.dry_run)
    print(json.dumps([{"inicio":r["inicio"],"fim":r["fim"],
                      "registros":r["registros"],"gravado":r["gravado"]}
                     for r in out],ensure_ascii=False))


if __name__=="__main__":
    main()
