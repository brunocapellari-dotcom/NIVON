"""View BigQuery mensal de corredores ferroviários sobre snapshots ANTT existentes.

Não cria dataset/bucket nem carrega toneladas. Opt-in explícito para DDL.
Fonte: vw_antt_ferrovia_od_atual (uma versão por ano, criada pelo coletor GCP).
"""
from __future__ import annotations

import argparse
import json
import sys

from .antt_bigquery import DestinoBQ
from .transporte_multimodal import ErroTransporte


def nome_view(destino: DestinoBQ) -> str:
    return f"{destino.projeto}.{destino.dataset}.vw_nivon_corredores_ferrovia_mensal"


def sql_view_corredores(destino: DestinoBQ) -> str:
    # Todos os identificadores foram validados no contrato DestinoBQ.
    # Matching explícito e restrito aos NOMES de estação, sem geocodificação falsa.
    src=destino.view_completa
    tgt=nome_view(destino)
    return f"""CREATE OR REPLACE VIEW \x60{tgt}\x60 AS
WITH base AS (
  SELECT
    competencia, data_referencia, data_coleta, arquivo_sha256,
    ferrovia, mercadoria, estacao_origem, uf_origem,
    estacao_destino, uf_destino, toneladas_uteis,
    CASE
      WHEN uf_origem='MT' AND LOWER(TRIM(estacao_origem)) IN ('rondonópolis','rondonopolis')
        THEN 'MT_RONDONOPOLIS_FERRO'
      WHEN uf_origem='MT' AND LOWER(TRIM(estacao_origem))='itiquira'
        THEN 'MT_ITIQUIRA_FERRO'
      WHEN uf_origem='MT' AND LOWER(TRIM(estacao_origem))='alto araguaia'
        THEN 'MT_ALTO_ARAGUAIA_FERRO'
      WHEN uf_origem='MT' AND LOWER(TRIM(estacao_origem))='dom aquino'
        THEN 'MT_DOM_AQUINO_BR070'
      ELSE NULL
    END polo_id,
    CASE
      WHEN LOWER(TRIM(mercadoria)) IN ('soja','grãos - soja','graos - soja','soja em grãos','soja em graos','soja em grao')
        THEN 'SOJA_EM_GRAO'
      WHEN LOWER(TRIM(mercadoria)) IN ('milho','grãos - milho','graos - milho','milho em grãos','milho em graos','milho em grao')
        THEN 'MILHO_EM_GRAO'
      WHEN LOWER(TRIM(mercadoria)) IN ('farelo de soja','farelo soja')
        THEN 'FARELO_SOJA'
      WHEN LOWER(TRIM(mercadoria)) IN ('óleo de soja','oleo de soja','oleo soja')
        THEN 'OLEO_SOJA'
      WHEN LOWER(TRIM(mercadoria))='açúcar' OR LOWER(TRIM(mercadoria))='acucar'
        THEN 'ACUCAR'
      WHEN LOWER(TRIM(mercadoria)) IN ('óleo diesel','oleo diesel')
        THEN 'DERIVADOS_PETROLEO'
      ELSE NULL
    END produto_normalizado
  FROM \x60{src}\x60
  WHERE natureza_tu='OBSERVADO_DECLARADO'
    AND data_referencia IS NOT NULL
),
filtrada AS (
  SELECT * FROM base WHERE polo_id IS NOT NULL
)
SELECT
  DATE_TRUNC(data_referencia, MONTH) AS data_referencia,
  competencia,
  polo_id, ferrovia, estacao_origem, uf_origem,
  mercadoria AS mercadoria_antt, produto_normalizado,
  estacao_destino, uf_destino,
  SUM(toneladas_uteis) AS toneladas_uteis,
  COUNT(1) AS linhas_fonte,
  ARRAY_AGG(DISTINCT arquivo_sha256 ORDER BY arquivo_sha256) AS arquivos_sha256,
  MAX(data_coleta) AS data_coleta,
  CAST(NULL AS DATE) AS data_publicacao,
  'ANTT_SIADE_ORIGEM_DESTINO' AS fonte,
  'FERROVIAS_FEDERAIS_CONCEDIDAS' AS abrangencia,
  'ESTACAO_NOME_EXATO_NAO_TERMINAL' AS match_geografico,
  FALSE AS transbordo_confirmado
FROM filtrada
GROUP BY
  data_referencia, competencia, polo_id, ferrovia, estacao_origem, uf_origem,
  mercadoria_antt, produto_normalizado, estacao_destino, uf_destino
"""


def publicar_view(destino: DestinoBQ, *, habilitar_ddl=False, cliente=None, sdk=None):
    statement=sql_view_corredores(destino)
    if not habilitar_ddl:
        return {"estado":"DRY_RUN_SEM_CONEXAO_GCP","destino":nome_view(destino),
                "dependencia":destino.view_completa}
    if cliente is None:
        try:
            from google.cloud import bigquery as sdk
        except ImportError:
            raise ErroTransporte("SDK BigQuery ausente") from None
        cliente=sdk.Client(project=destino.projeto)
    elif sdk is None:
        raise ErroTransporte("SDK de validação requerido para cliente injetado")
    # Falhar fechado se recursos de upstream não existem. Sem criar projetos/datasets.
    cliente.get_dataset(f"{destino.projeto}.{destino.dataset}")
    upstream=cliente.get_table(destino.view_completa)
    if getattr(upstream,"table_type",None)!="VIEW":
        raise ErroTransporte("view atual de origem SIADE não encontrada ou contrato divergente")
    q=sdk.QueryJobConfig(maximum_bytes_billed=50_000_000)
    job=cliente.query(statement,job_config=q)
    job.result(timeout=120)
    if getattr(job,"errors",None):
        raise ErroTransporte("criação da view mensal falhou")
    return {"estado":"VIEW_CRIADA_NAO_HOMOLOGADA","view":nome_view(destino),
            "job_id":job.job_id,"fonte":destino.view_completa,
            "validacao":"CRUZAR_TOTAIS_MENSAL_COM_SOURCE_SIADE"}


def main(argv=None):
    p=argparse.ArgumentParser(description="View mensal corredores ferroviários ANTT no BigQuery")
    p.add_argument("--projeto",required=True)
    p.add_argument("--dataset",required=True)
    p.add_argument("--live",action="store_true")
    args=p.parse_args(argv)
    try:
        doc=publicar_view(DestinoBQ(args.projeto,args.dataset),habilitar_ddl=args.live)
        print(json.dumps(doc,ensure_ascii=False))
        return 0
    except (ErroTransporte,OSError,ValueError) as exc:
        print(json.dumps({"estado":"BLOQUEIO_SEGURANCA_OU_FONTE","classe":type(exc).__name__}),
              file=sys.stderr)
        return 2

if __name__=="__main__":
    raise SystemExit(main())
