"""NIVON: ativação conjunta e idempotente das DUAS tabelas de fontes GCP.

Utiliza APENAS as rotinas oficiais já presentes na main:
  preflight_gcp_fontes.verificar_nuvem (observações canônicas)
  agro_staging_bigquery.verificar_ou_criar_tabela (quarentena IMEA/CONAB)

Não cria projeto, dataset ou bucket. Não consulta fontes, não carrega linhas,
não altera dados existentes e não assume que booleans provam IAM/custo.
"""
from __future__ import annotations

import argparse
import json
import os

from .preflight_gcp_fontes import validar_config, verificar_nuvem
from .agro_staging_bigquery import verificar_ou_criar_tabela
from .carga_bigquery_fontes import ErroCargaBigQuery


class ErroAtivacaoGCP(ValueError):
    pass


def ativar_destinos(*, projeto: str, dataset: str, bucket: str,
                   aplicar: bool = False, autorizado: bool = False,
                   canonical=None, staging=None) -> dict:
    """Confere ou cria somente tabelas no dataset existente.

    Modo consulta: relata ausência de cada tabela sem encerramento antecipado
    após descobrir que a primeira falta.
    Modo aplicar: exige autorização; em falha intermediária não faz rollback
    destrutivo e a repetição retoma idempotentemente.
    """
    validar_config(projeto=projeto, dataset=dataset, bucket=bucket)
    if type(aplicar) is not bool or type(autorizado) is not bool:
        raise ErroAtivacaoGCP("aplicar/autorizado precisam ser booleanos")
    if aplicar and not autorizado:
        raise PermissionError("ativação BigQuery não aprovada; não criar tabelas")
    chk = canonical or verificar_nuvem
    stage = staging or verificar_ou_criar_tabela
    # Caso não exista, a rotina oficial canônica lança erro em modo read-only.
    try:
        a = chk(projeto=projeto, dataset=dataset, bucket=bucket,
                criar_tabela=aplicar)
        if a.get("tabela_validada") is not True:
            raise ErroAtivacaoGCP("tabela canônica sem schema aprovado")
        canonico = {
            "estado": "SCHEMA_VALIDADO",
            "tabela": f"{projeto}.{dataset}.nivon_observacoes",
            "criada_neste_lote": a.get("tabela_criada") is True,
        }
    except ErroCargaBigQuery as exc:
        if aplicar or "tabela BigQuery ausente" not in str(exc):
            raise
        canonico = {
            "estado": "TABELA_AUSENTE",
            "tabela": f"{projeto}.{dataset}.nivon_observacoes",
            "criada_neste_lote": False,
        }
    b = stage(projeto=projeto, dataset=dataset, verificar=True,
              aplicar=aplicar, aprovado=autorizado)
    if not isinstance(b, dict) or b.get("estado") not in {
        "SCHEMA_VALIDADO", "TABELA_AUSENTE"
    }:
        raise ErroAtivacaoGCP("staging não retornou contrato de verificação")
    if aplicar and b["estado"]!="SCHEMA_VALIDADO":
        raise ErroAtivacaoGCP("tabela de staging não validada após criação")
    agro = {
        "estado": b["estado"],
        "tabela": f"{projeto}.{dataset}.agro_publicacoes_staging",
        "criada_neste_lote": b.get("criou_tabela") is True,
        "data_referencia_opcional": True,
        "publicavel_como_dado_canonico": False,
    }
    ready = canonico["estado"]=="SCHEMA_VALIDADO" and agro["estado"]=="SCHEMA_VALIDADO"
    return {
        "status": "DESTINOS_BIGQUERY_VERIFICADOS" if ready
                  else "FALTAM_TABELAS_BIGQUERY",
        "projeto": projeto, "dataset": dataset, "bucket": bucket,
        "canonico": canonico, "agro_quarentena": agro,
        "escrita_tabelas_solicitada": aplicar,
        "tabelas_operacionais_verificadas": ready,
        "carregou_dados": False, "executou_consulta_sql": False,
        "verificou_permissao_de_gravacao_em_linhas": False,
        "go_live": False,
    }


def main(argv=None) -> int:
    p=argparse.ArgumentParser(description="NIVON: ativar tabelas GCP existentes/faltantes")
    p.add_argument("--projeto",required=True)
    p.add_argument("--dataset",required=True)
    p.add_argument("--bucket",required=True)
    p.add_argument("--aplicar",action="store_true")
    p.add_argument("--executar-preflight",action="store_true")
    opts=p.parse_args(argv)
    if opts.aplicar and not opts.executar_preflight:
        raise PermissionError("--aplicar exige --executar-preflight")
    if not opts.executar_preflight:
        out={
            "status":"PLANO_LOCAL_SEM_CONEXAO",
            "projeto":validar_config(projeto=opts.projeto,dataset=opts.dataset,
                                    bucket=opts.bucket)["projeto"],
            "destinos": ["nivon_observacoes","agro_publicacoes_staging"],
            "criou_tabelas":False,"consultou_cloud":False,
        }
    else:
        env=os.environ
        approved=all(env.get(k)=="true" for k in (
            "NIVON_BQ_BOOTSTRAP_TABLE_APPROVED",
            "NIVON_AGRO_STAGING_SCHEMA_APPROVED",
            "NIVON_AGRO_GCP_WRITE_APPROVED",
            "NIVON_ZERO_COST_BQ_APPROVED",
        ))
        out=ativar_destinos(
            projeto=opts.projeto,dataset=opts.dataset,bucket=opts.bucket,
            aplicar=opts.aplicar,autorizado=approved)
    print(json.dumps(out,ensure_ascii=False,indent=2))
    return 0 if out["status"] not in {"FALTAM_TABELAS_BIGQUERY"} else 2


if __name__=="__main__":
    raise SystemExit(main())
