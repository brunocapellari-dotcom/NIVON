-- NIVON | Central Agro Brasil/Argentina | Contrato de staging BigQuery
-- DDL para execucao MANUAL depois de configurar Google Cloud, IAM e custos.
-- Nao ha implantacao automatica nem habilitacao de billing por este arquivo.
-- Valores decimais sao STRING na landing para preservar precisao.
-- SAFE_CAST/NUMERIC somente apos validacao de esquema e valores.
CREATE TABLE IF NOT EXISTS `${PROJECT_ID}.${DATASET_ID}.agro_fonte_stage`
(
  source_id STRING NOT NULL,
  dataset_id STRING NOT NULL,
  indicador_id STRING NOT NULL,
  pais STRING NOT NULL,
  produto STRING NOT NULL,
  safra STRING,
  regiao STRING,
  competencia STRING,
  unidade STRING NOT NULL,
  valor STRING NOT NULL,
  data_publicacao_original STRING,
  data_declaracao STRING,
  coletado_utc TIMESTAMP NOT NULL,
  source_sha256 STRING NOT NULL,
  hash_natureza STRING NOT NULL,
  classe STRING NOT NULL,
  qualidade STRING NOT NULL,
  nivel_agregacao STRING NOT NULL,
  status STRING NOT NULL
)
PARTITION BY DATE(coletado_utc)
CLUSTER BY source_id, dataset_id, produto, source_sha256
OPTIONS(description='Landing NIVON quarentena. Nao fonte validada para publicacao.');

-- BigQuery nao garante UNIQUE; deduplicar antes de carregar.
-- Nenhuma soma entre vintages da mesma operacao SIO: dupla contagem.
-- Datas de publicacao desconhecidas NULL e nao inferidas de coleta.
-- IDs individuais HMAC do SIO nao saem do SQLite local.
