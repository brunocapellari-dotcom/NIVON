-- NIVON: staging de migracao historica do Neon, sem alterar dados de origem.
-- BigQuery na regiao us-central1; codigo principal nunca infere data_referencia a partir de data_publicacao.
-- Executar apos gcloud verificar projeto, faturamento e permissoes.
CREATE SCHEMA IF NOT EXISTS `nivon-data.nivon_stage`
OPTIONS(location="us-central1",description="NIVON: rastreabilidade das migracoes e entradas nao canonicas");

CREATE TABLE IF NOT EXISTS `nivon-data.nivon_stage.neon_legado` (
  id_registro STRING NOT NULL OPTIONS(description="SHA256 identificador logico da linha e vintage"),
  fonte STRING NOT NULL,
  dataset_origem STRING NOT NULL,
  id_legado INT64 NOT NULL,
  chave_origem STRING NOT NULL,
  hash_versao STRING NOT NULL,
  payload_sha256 STRING NOT NULL OPTIONS(description="SHA256 payload normalizado, NAO hash de RAW primario"),
  payload_json STRING NOT NULL OPTIONS(description="JSON privado historizado; nao divulgar publicamente"),
  data_particao DATE NOT NULL OPTIONS(description="Referencia ou publicacao ou coleta; ver tipo_referencia"),
  data_referencia DATE OPTIONS(description="NULL quando origem nao comprovou referencia economica"),
  data_publicacao DATE OPTIONS(description="Dia informado; nao assumir horario/fuso se ausente"),
  data_coleta TIMESTAMP NOT NULL,
  competencia STRING,
  natureza STRING NOT NULL,
  status_qualidade STRING NOT NULL,
  source_url STRING,
  tipo_referencia STRING NOT NULL,
  origem_sha256 STRING OPTIONS(description="NULL se hash bruto primario nao disponivel")
)
PARTITION BY data_particao
CLUSTER BY fonte,dataset_origem,chave_origem
OPTIONS(require_partition_filter=TRUE,
description="NIVON historico legado somente staging: CEPEA, IMEA, CONAB. Nao alimentar precos atuais sem gate.");
