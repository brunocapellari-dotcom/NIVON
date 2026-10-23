-- ANTT / NIVON: tabela de referência anual (top-16 RGIs).
-- Substituir PROJECT_ID.DATASET_ID pelo destino autorizado.
-- Não misturar com MDF-e mensal nem carregar dados sintéticos.
CREATE TABLE IF NOT EXISTS `PROJECT_ID.DATASET_ID.antt_anuario_rgi` (
  sha256 STRING NOT NULL,
  ano INT64 NOT NULL,
  origem_uf STRING NOT NULL,
  origem_rgi STRING NOT NULL,
  destino_uf STRING NOT NULL,
  destino_rgi STRING NOT NULL,
  toneladas INT64 NOT NULL,
  participacao_pct NUMERIC,
  data_referencia DATE NOT NULL,
  competencia STRING NOT NULL,
  data_publicacao DATE,
  data_coleta TIMESTAMP NOT NULL,
  fonte STRING NOT NULL,
  classificacao STRING NOT NULL,
  escopo STRING NOT NULL,
  granularidade STRING NOT NULL
)
PARTITION BY data_referencia
CLUSTER BY origem_uf, destino_uf, origem_rgi, destino_rgi;
