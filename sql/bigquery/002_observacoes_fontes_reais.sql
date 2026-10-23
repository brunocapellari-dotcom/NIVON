-- NIVON: historico de observacoes de fontes novas.
-- DDL preparado, NAO EXECUTADO. Substituir ID do projeto e dataset confirmados.
-- A tabela guarda revisoes; ausencias nao se tornam zeros.
CREATE TABLE IF NOT EXISTS `${PROJECT_ID}.${DATASET_ID}.nivon_observacoes` (
  dataset_id STRING NOT NULL,
  identidade STRING NOT NULL,
  fingerprint STRING NOT NULL,
  referencia STRING NOT NULL,
  data_referencia DATE NOT NULL,
  competencia STRING,
  publicacao STRING,
  data_publicacao TIMESTAMP,
  coletado_em STRING NOT NULL,
  data_coleta TIMESTAMP NOT NULL,
  unidade STRING,
  valor STRING,
  campos JSON NOT NULL,
  snapshot_id STRING NOT NULL,
  natureza STRING NOT NULL
)
PARTITION BY data_referencia
CLUSTER BY dataset_id, identidade, fingerprint
OPTIONS (
  description='NIVON: observacoes informadas/observadas versionadas por fingerprint e SHA RAW; sem promocao editorial automatica'
);

-- Loader explicito: SQL MERGE pela chave
-- (dataset_id, identidade, fingerprint), guardando todas as revisoes.
-- A tabela fisica BigQuery NAO garante UNIQUE: loader deduplica por chave.
