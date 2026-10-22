-- NIVON — DDL de contrato FAOSTAT QCL (NÃO executar automaticamente)
--
-- Substituir ${PROJECT_ID} e ${DATASET_ID} SOMENTE depois de validar IAM,
-- região, dataset existente, Free Tier e aprovação para possível cobrança.
-- Projeto informado em contexto: nivon-data; dataset ainda não verificado.
--
-- Cada linha é uma edição do indicador identificada por source_sha256.
-- BigQuery não impõe chaves únicas: usar MERGE/deduplicação no futuro loader.
-- data_referencia para observação anual = 31 de dezembro do ano referência;
-- data_publicacao NULL até evidência real de sua divulgação por observação.

CREATE TABLE IF NOT EXISTS `${PROJECT_ID}.${DATASET_ID}.faostat_qcl_snapshots`
(
  dataset_id STRING NOT NULL,
  source_id STRING NOT NULL,
  dominio STRING NOT NULL,
  pais STRING NOT NULL,
  cultura STRING NOT NULL,
  area_code STRING NOT NULL,
  item_code STRING NOT NULL,
  element_code STRING NOT NULL,
  ano INT64 NOT NULL,
  unidade STRING NOT NULL,
  valor NUMERIC NOT NULL,
  flag_fonte STRING,
  data_referencia DATE NOT NULL,
  competencia STRING NOT NULL,
  data_publicacao TIMESTAMP,
  data_coleta TIMESTAMP NOT NULL,
  data_atualizacao_fonte DATETIME NOT NULL,
  source_sha256 STRING NOT NULL
)
PARTITION BY data_referencia
CLUSTER BY pais, cultura, element_code, source_sha256
OPTIONS (
  description = 'FAOSTAT QCL historico versionado por SHA de arquivo. Dado anual; sem auto-publicacao.'
);

-- Staging futura: MERGE por (dataset_id,pais,cultura,element_code,ano,source_sha256).
-- Nunca sobrescrever versão histórica apenas porque o valor mudou.
-- Não confundir data_atualizacao_fonte com data_publicacao.
