-- NIVON: publicacoes IMEA e CONAB com referencia de periodo desconhecida.
-- SQL preparado, NAO executado. Criacao da tabela requer aprovacao de custo,
-- direitos, IAM e DDL do projeto/dataset privado.
-- Substituir ${PROJECT_ID} e ${DATASET_ID} somente por IDs confirmados.
-- NUNCA executar MERGE destas linhas em nivon_observacoes canônica.

CREATE TABLE IF NOT EXISTS `${PROJECT_ID}.${DATASET_ID}.agro_publicacoes_staging` (
  dataset_id STRING NOT NULL,
  snapshot_id STRING NOT NULL,
  identidade STRING NOT NULL,
  fingerprint STRING NOT NULL,
  origem_url STRING NOT NULL,
  referencia_tecnica STRING NOT NULL,
  data_referencia DATE,
  data_publicacao DATE,
  publicacao_bruta STRING,
  data_coleta TIMESTAMP NOT NULL,
  competencia STRING,
  natureza STRING NOT NULL,
  unidade STRING,
  valor STRING,
  campos JSON NOT NULL,
  estado STRING NOT NULL
)
PARTITION BY DATE(data_coleta)
CLUSTER BY dataset_id, identidade, snapshot_id
OPTIONS (
  description = 'NIVON: observacoes IMEA/CONAB QUARANTINED, sem referencia verdadeira; nao promover ao dado canonico'
);
