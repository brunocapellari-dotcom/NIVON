-- NIVON ZARC Mato Grosso — backup estruturado historico do Neon.
-- Preservar "nao homologado" e nao usar no motor agronomico apenas porque a carga passou.
CREATE TABLE IF NOT EXISTS `nivon-data.nivon_stage.zarc_linhas_mt` (
  source_sha256 STRING NOT NULL OPTIONS(description="SHA256 da origem ZARC; chave composta com linha_fisica"),
  linha_fisica INT64 NOT NULL,
  municipio_ibge STRING NOT NULL,
  chave_logica_sha STRING NOT NULL,
  conteudo_sha STRING NOT NULL,
  payload_json STRING NOT NULL OPTIONS(description="Linha completa mais dados_raw em JSON privado"),
  payload_sha256 STRING NOT NULL OPTIONS(description="Hash de transporte normalizado, nao prova de RAW"),
  data_particao DATE NOT NULL,
  data_referencia DATE,
  data_publicacao DATE,
  data_coleta TIMESTAMP NOT NULL,
  competencia STRING,
  direitos_revisados BOOL NOT NULL,
  dados_agronomicos_homologados BOOL NOT NULL,
  raw_backup_verificado BOOL NOT NULL,
  apto_modelo BOOL NOT NULL,
  tipo_coleta STRING NOT NULL
)
PARTITION BY data_particao
CLUSTER BY source_sha256,municipio_ibge
OPTIONS(require_partition_filter=TRUE,
  description="ZARC legado privado do NIVON; aprovacao agronomica separada da integridade de transporte.");
