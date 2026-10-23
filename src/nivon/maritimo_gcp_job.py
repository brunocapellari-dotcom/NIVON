"""Ponto de entrada de um Cloud Run Job do NIVON, sem chaves estáticas.

O job só executa com NIVON_MARITIMO_COLETA_HABILITADA=true.
Coleta -> arquiva HTML/PortWatch -> staging SQLite -> BigQuery.
"""
from __future__ import annotations

import json
import os
import tempfile
from datetime import datetime,timezone,timedelta
from pathlib import Path

from nivon.maritimo_pipeline import HistoricoMaritimo
from nivon.maritimo_lote import executar_lote, executar_portwatch
from nivon.maritimo_bigquery import sincronizar_bigquery
from nivon.maritimo_cloud_storage import ArquivoMaritimoGCS

FONTES=("suape","imbituba","santarem_cdp","vila_conde_cdp")
PASSAGENS=("hormuz","bab_el_mandeb","suez","panama")

def executar_job(*, env=None, storage_client=None, bigquery_client=None,
                bigquery_module=None, fornecedor_html=None, fornecer_portwatch=None):
    variables=os.environ if env is None else env
    if variables.get("NIVON_MARITIMO_COLETA_HABILITADA")!="true":
        raise PermissionError("job nao habilitado; nenhuma coleta iniciada")
    # Reutilizar contrato de configuracao do NIVON para Google Cloud
    # compartilhado com os outros coletores (PR de Fontes GCP).
    projeto=variables.get("GOOGLE_CLOUD_PROJECT") or variables.get("NIVON_BQ_PROJECT")
    dataset=(variables.get("NIVON_MARITIMO_DATASET") or
             variables.get("NIVON_BQ_DATASET") or "nivon_raw")
    bucket=variables.get("NIVON_MARITIMO_BUCKET") or variables.get("NIVON_GCS_BUCKET")
    # Validar o projeto ANTES de arquivar qualquer evidencia no GCS:
    # nunca executar coleta no projeto incorreto ou indeterminado.
    from nivon.maritimo_bigquery import validar_destino
    validar_destino(projeto,dataset)
    if not bucket:
        raise ValueError("NIVON_MARITIMO_BUCKET obrigatorio")
    # Primeiros lotes podem homologar 1 fonte por vez; nunca aceitar
    # nomes livres ou extrapolar o conjunto de coletores auditados.
    from nivon.maritimo_pipeline import HTML_AUTORIZADO
    selected=variables.get("NIVON_MARITIMO_FONTES","").strip()
    fontes=tuple(v.strip() for v in selected.split(",")) if selected else FONTES
    if not fontes or len(fontes)!=len(set(fontes)) or any(f not in HTML_AUTORIZADO for f in fontes):
        raise ValueError("lista de fontes para homologacao nao autorizada")
    armazenar=ArquivoMaritimoGCS(bucket,storage_client=storage_client)
    today=datetime.now(timezone.utc).date()
    with tempfile.TemporaryDirectory(prefix="nivon-maritimo-") as dirname:
        db_path=Path(dirname)/"capturas.sqlite"
        pw_path=Path(dirname)/"portwatch.sqlite"
        db=HistoricoMaritimo(db_path)
        snapshots=[]
        execucoes=[]
        try:
            def snapshot(fonte,html,data):
                item=armazenar.arquivar(fonte,html,coletado_em=data)
                snapshots.append({"fonte":fonte,"coletado_em":data,**item})
            result=executar_lote(fontes,db,fornecedor_html=fornecedor_html,
                 permitir_rede=fornecedor_html is None,on_snapshot=snapshot)
            execucoes.extend(result["fontes"])
            if variables.get("NIVON_PORTWATCH_COLETA_HABILITADA")=="true":
                start=(today-timedelta(days=8)).isoformat()
                end=(today-timedelta(days=1)).isoformat()
                def archive_pw(url,payload,offset):
                    at=datetime.now(timezone.utc).isoformat()
                    item=armazenar.arquivar("fmi_portwatch",payload,coletado_em=at)
                    snapshots.append({"fonte":"fmi_portwatch","coletado_em":at,**item})
                portwatch=executar_portwatch(PASSAGENS,start,end,
                   banco_lineups=db,banco_portwatch=pw_path,
                   fornecer_json=fornecer_portwatch,
                   permitir_rede=fornecer_portwatch is None,
                   archivador_pagina=archive_pw)
                result["portwatch_estado"]=portwatch["estado"]
                # PortWatch gera seu proprio run_id e a execucao real
                # deve ser preservada no manifesto.
                execucoes.append(portwatch)
        finally:
            db.fechar()
        manifesto=armazenar.gravar_manifesto(
            run_id=result["run_id"],snapshots=snapshots,
            execucoes=execucoes,portwatch_estado=result.get("portwatch_estado"))
        bigquery=sincronizar_bigquery(db_path,
            portwatch_banco=pw_path if pw_path.is_file() else None,
            projeto=projeto,dataset=dataset,
            client=bigquery_client,bigquery_module=bigquery_module,
            localizacao=variables.get("NIVON_GCP_REGION") or "southamerica-east1")
        # Erros recuperaveis por reprocessamento dos objetos GCS.
        return {"estados":result["estados"],"portwatch":result.get("portwatch_estado"),
                "persistencia":bigquery,"manifesto":manifesto,"apto_operacao":
                 result["apto_operacao"] and result.get("portwatch_estado","OK")=="OK"}

def main():
    result=executar_job()
    print(json.dumps({"estados":result["estados"],
        "persistido_bigquery":result["persistencia"]["gravado"],
        "apto_operacao":result["apto_operacao"]},sort_keys=True))
    if not result["apto_operacao"]:
        raise SystemExit(2)

if __name__=="__main__":
    main()
