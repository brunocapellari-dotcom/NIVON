"""Ensaio controlado NIVON: um ano/indicador WDI -> GCS -> BigQuery -> readback.

Sem dados sintéticos em produção. Não cria tabela nem altera IAM. Opt-in
manual mais 4 gates; preflight ocorre antes de GET externo ou escrita GCP.
"""
from __future__ import annotations

import argparse
import json
import os
import tempfile
from pathlib import Path

from .preflight_gcp_fontes import validar_config, verificar_nuvem
from .coletores_agro_ibge_wdi import coletar_wdi
from .ingestao_fontes_reais import exportar_jsonl
from .arquivo_raw_gcs import arquivar_gcs
from .lote_cloud_recuperavel import arquivar_stage
from .carga_bigquery_fontes import executar_carga
from .verificacao_cloud_fontes import verificar_publicacao

FONTE="WORLD_BANK_AGRO_INDICADORES"
INDICADOR="AG.YLD.CREL.KG"
ANO=2024
GATES=("NIVON_PILOTO_WDI_GCP_APPROVED",
       "NIVON_ZERO_COST_BQ_APPROVED",
       "NIVON_RAW_ARCHIVE_APPROVED",
       "NIVON_RECOVERABLE_STAGE_APPROVED")


class ErroPilotoGCP(ValueError):
    pass


def executar_piloto(*,projeto,dataset,bucket,executar=False,env=None,
                    preflight=None,coletor=None,exportador=None,
                    raw_uploader=None,stage_uploader=None,loader=None,
                    verificador=None):
    validar_config(projeto=projeto,dataset=dataset,bucket=bucket)
    plano={"fonte":FONTE,"pais":"BRA","indicador":INDICADOR,
           "ano":ANO,"projeto":projeto,"dataset":dataset,
           "bucket":bucket,"executado":False,"sem_dados_ficticios":True}
    if executar is not True:
        return {**plano,"estado":"PLANO_SEM_REDE_NEM_ESCRITA"}
    ambient=os.environ if env is None else env
    ausentes=[k for k in GATES if ambient.get(k)!="true"]
    if ausentes:
        raise PermissionError("piloto bloqueado; gates ausentes: "+", ".join(ausentes))
    pf=verificar_nuvem if preflight is None else preflight
    collect=coletar_wdi if coletor is None else coletor
    exp=exportar_jsonl if exportador is None else exportador
    upraw=arquivar_gcs if raw_uploader is None else raw_uploader
    upstage=arquivar_stage if stage_uploader is None else stage_uploader
    load=executar_carga if loader is None else loader
    check=verificar_publicacao if verificador is None else verificador
    validado=pf(projeto=projeto,dataset=dataset,bucket=bucket,criar_tabela=False)
    if validado.get("tabela_validada") is not True:
        raise ErroPilotoGCP("tabela canônica não homologada no preflight")
    with tempfile.TemporaryDirectory(prefix="nivon-piloto-wdi-") as base:
        root=Path(base)
        banco=root/"piloto.sqlite"
        raw=root/"raw"
        saida=collect(pais="BRA",indicador=INDICADOR,inicio=ANO,fim=ANO,
                      banco=banco,raw_dir=raw,executar=True)
        if (saida.get("estado")!="NORMALIZED" or
                saida.get("total_observacoes_no_lote")!=1 or
                saida.get("novas_observacoes")!=1):
            raise ErroPilotoGCP("resposta WDI incompleta/duplicada; não arquivar")
        stage=exp(banco=banco,destino=root/"piloto.jsonl",dataset_id=FONTE)
        if stage.get("observacoes")!=1:
            raise ErroPilotoGCP("stage exige exatamente uma observação real")
        recibo_raw=upraw(banco=banco,raw_dir=raw,bucket=bucket,executar=True)
        if recibo_raw.get("executado") is not True or recibo_raw.get("objetos_verificados")!=1:
            raise ErroPilotoGCP("RAW GCS não confirmado; MERGE proibido")
        manifesto=upstage(banco=banco,arquivo_jsonl=stage["arquivo"],
                          bucket=bucket,projeto=projeto,dataset=dataset,executar=True)
        if manifesto.get("executado") is not True or not manifesto.get("manifesto_sha256"):
            raise ErroPilotoGCP("manifesto recuperável ausente; MERGE proibido")
        carga=load(arquivo=stage["arquivo"],project_id=projeto,
                   dataset_id=dataset,executar=True)
        if carga.get("executado") is not True or carga.get("linhas_enviadas")!=1:
            raise ErroPilotoGCP("BigQuery não confirmou envio")
        verificado=check(banco=banco,raw_dir=raw,bucket=bucket,
                        arquivo_jsonl=stage["arquivo"],project_id=projeto,
                        dataset_id=dataset,executar=True)
        if (verificado.get("executado") is not True or
            verificado.get("amostras_bigquery_confirmadas")!=1 or
            verificado.get("objetos_gcs_confirmados")!=1):
            raise ErroPilotoGCP("leitura de confirmação GCS/BigQuery incompleta")
        return {**plano,"executado":True,"estado":"PILOTO_WDI_CONFIRMACAO_E2E",
            "observacoes_reais":1,"raw_sha256":saida["sha256"],
            "manifesto_sha256":manifesto["manifesto_sha256"],
            "gcs_confirmado":True,"bigquery_confirmado":True,
            "dados_publicados_externamente":False,
            "nao_autoriza_coletas_amplas":True}


def main(argv=None):
    parser=argparse.ArgumentParser(description="Pilotar GCS/BigQuery com 1 ano WDI")
    parser.add_argument("--projeto",required=True)
    parser.add_argument("--dataset",required=True)
    parser.add_argument("--bucket",required=True)
    parser.add_argument("--executar",action="store_true")
    args=parser.parse_args(argv)
    out=executar_piloto(projeto=args.projeto,dataset=args.dataset,bucket=args.bucket,
                       executar=args.executar)
    print(json.dumps(out,ensure_ascii=False,indent=2))
    return 0


if __name__=="__main__":
    raise SystemExit(main())
