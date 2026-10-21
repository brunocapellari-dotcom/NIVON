-- NIVON / Google Cloud BigQuery - ESQUEMA MODELO, NAO EXECUTAR AUTOMATICAMENTE.
-- Substituir ${PROJECT_ID} por identificador de projeto verificado apos aprovacao do deploy.
-- Somente dados cuja coleta E ARMAZENAMENTO sejam autorizados. Sem dados sintéticos em producao.
-- As chaves logicas exigem idempotencia no pipeline; BigQuery nao aplica UNIQUE automaticamente.

CREATE SCHEMA IF NOT EXISTS `${PROJECT_ID}.nivon_control`
OPTIONS(location = "us-central1");

CREATE SCHEMA IF NOT EXISTS `${PROJECT_ID}.nivon_core`
OPTIONS(location = "us-central1");

CREATE SCHEMA IF NOT EXISTS `${PROJECT_ID}.nivon_models`
OPTIONS(location = "us-central1");

CREATE TABLE IF NOT EXISTS `${PROJECT_ID}.nivon_control.raw_manifest` (
  raw_id STRING NOT NULL,
  fonte_id STRING NOT NULL,
  dataset_id STRING NOT NULL,
  gcs_uri STRING NOT NULL,
  origem_sha256 STRING NOT NULL,
  tamanho_bytes INT64 NOT NULL,
  formato STRING NOT NULL,
  schema_versao STRING NOT NULL,
  vintage_id STRING NOT NULL,
  competencia STRING,
  data_referencia DATE NOT NULL,
  data_publicacao TIMESTAMP,
  data_coleta TIMESTAMP NOT NULL,
  natureza STRING NOT NULL,
  status_qualidade STRING NOT NULL,
  evidencia_licenca STRING NOT NULL,
  autorizacao_armazenamento BOOL NOT NULL,
  metadados JSON
)
PARTITION BY data_referencia
CLUSTER BY dataset_id, fonte_id
OPTIONS(require_partition_filter = TRUE,
  description = "Manifesto imutavel dos arquivos originais; a URI requer objeto privado e SHA verificado.");

CREATE TABLE IF NOT EXISTS `${PROJECT_ID}.nivon_control.ingestao_runs` (
  run_id STRING NOT NULL,
  dataset_id STRING NOT NULL,
  coletor_versao STRING NOT NULL,
  data_coleta TIMESTAMP NOT NULL,
  data_inicio TIMESTAMP NOT NULL,
  data_fim TIMESTAMP,
  status STRING NOT NULL,
  linhas_lidas INT64,
  linhas_validas INT64,
  linhas_rejeitadas INT64,
  erro_classe STRING,
  erro_resumo_sanitizado STRING
)
PARTITION BY DATE(data_coleta)
CLUSTER BY dataset_id, status
OPTIONS(require_partition_filter = TRUE,
  description = "Ledger de execucoes sem segredos nem payloads reais.");

CREATE TABLE IF NOT EXISTS `${PROJECT_ID}.nivon_core.observacoes` (
  observacao_id STRING NOT NULL,
  fonte_id STRING NOT NULL,
  dataset_id STRING NOT NULL,
  indicador_id STRING NOT NULL,
  produto_id STRING,
  regiao_id STRING,
  unidade STRING NOT NULL,
  valor NUMERIC,
  valor_texto STRING,
  competencia STRING,
  data_referencia DATE NOT NULL,
  instante_referencia TIMESTAMP,
  data_publicacao TIMESTAMP,
  data_coleta TIMESTAMP NOT NULL,
  origem_sha256 STRING NOT NULL,
  schema_versao STRING NOT NULL,
  vintage_id STRING NOT NULL,
  natureza STRING NOT NULL,
  status_qualidade STRING NOT NULL,
  amostra BOOLEAN,
  atributos JSON
)
PARTITION BY data_referencia
CLUSTER BY dataset_id, indicador_id, regiao_id, produto_id
OPTIONS(require_partition_filter = TRUE,
  description = "Fato temporal versionado para consultas as-of; desconhecido nao vira zero.");

CREATE TABLE IF NOT EXISTS `${PROJECT_ID}.nivon_models.previsoes` (
  previsao_id STRING NOT NULL,
  modelo_id STRING NOT NULL,
  modelo_versao STRING NOT NULL,
  indicador_id STRING NOT NULL,
  produto_id STRING,
  regiao_id STRING,
  data_referencia DATE NOT NULL,
  emitida_em TIMESTAMP NOT NULL,
  horizonte STRING NOT NULL,
  valor_previsto NUMERIC,
  limite_inferior NUMERIC,
  limite_superior NUMERIC,
  tendencia STRING,
  confianca FLOAT64,
  referencia_vintage_id STRING NOT NULL,
  data_coleta TIMESTAMP NOT NULL,
  natureza STRING NOT NULL,
  estado_validacao STRING NOT NULL
)
PARTITION BY data_referencia
CLUSTER BY indicador_id, modelo_id, regiao_id
OPTIONS(require_partition_filter = TRUE,
  description = "Projecoes com horizonte, versao, incerteza e emissao explicitos.");
