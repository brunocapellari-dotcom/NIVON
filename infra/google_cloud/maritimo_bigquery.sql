-- Schema analitico NIVON: projeto/dataset sao placeholders, NAO dados existentes.
-- Provisionar em BigQuery uma vez, com dataset na mesma localizacao dos jobs.
CREATE TABLE IF NOT EXISTS `NIVON_PROJECT_ID.NIVON_DATASET_ID.capturas` (
 fonte STRING NOT NULL, hash_conteudo STRING NOT NULL,
 primeiro_visto TIMESTAMP NOT NULL, ultimo_visto TIMESTAMP NOT NULL,
 quantidade INT64, qualidade_json STRING
) PARTITION BY DATE(primeiro_visto) CLUSTER BY fonte,hash_conteudo;

CREATE TABLE IF NOT EXISTS `NIVON_PROJECT_ID.NIVON_DATASET_ID.escalas_revisoes` (
 fonte STRING NOT NULL, escala_id STRING NOT NULL, revisao_sha256 STRING NOT NULL,
 data_referencia DATE, competencia STRING, data_publicacao TIMESTAMP,
 data_coleta TIMESTAMP NOT NULL, natureza STRING, situacao STRING,
 publicavel BOOL NOT NULL, payload_json STRING
) PARTITION BY data_referencia CLUSTER BY fonte,escala_id;

CREATE TABLE IF NOT EXISTS `NIVON_PROJECT_ID.NIVON_DATASET_ID.fluxos_passagens` (
 fonte STRING NOT NULL, passagem STRING NOT NULL, data_referencia DATE NOT NULL,
 revisao_sha256 STRING NOT NULL, data_coleta TIMESTAMP NOT NULL,
 transitos_ais INT64, volume_transito_estimado_t FLOAT64, payload_json STRING
) PARTITION BY data_referencia CLUSTER BY passagem,fonte;

CREATE TABLE IF NOT EXISTS `NIVON_PROJECT_ID.NIVON_DATASET_ID.coleta_execucoes` (
 run_id STRING NOT NULL, fonte STRING NOT NULL, data_coleta TIMESTAMP NOT NULL,
 estado STRING NOT NULL, quantidade INT64, revisoes INT64,
 captura_sha256 STRING, motivo STRING, duracao_ms INT64
) PARTITION BY DATE(data_coleta) CLUSTER BY fonte,estado;

CREATE OR REPLACE VIEW `NIVON_PROJECT_ID.NIVON_DATASET_ID.estado_fontes_v` AS
SELECT fonte, data_coleta ultima_coleta, estado ultimo_estado,
 quantidade registros_ultima_coleta, revisoes revisoes_ultima_coleta,
 motivo, IF(data_coleta < TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL 12 HOUR),
            'ATRASADA','RECENTE') frescor
FROM `NIVON_PROJECT_ID.NIVON_DATASET_ID.coleta_execucoes`
QUALIFY ROW_NUMBER() OVER(PARTITION BY fonte ORDER BY data_coleta DESC,run_id DESC)=1;
