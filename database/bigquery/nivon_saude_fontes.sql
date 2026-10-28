-- Saúde por execução do Cloud Run Job nivon-coletor (uma linha por fonte).
-- Executar uma vez, pelo dono, antes do primeiro deploy do coletor.
CREATE TABLE IF NOT EXISTS `nivon-data.nivon_core.saude_fontes` (
  execucao_id STRING NOT NULL,   -- CLOUD_RUN_EXECUTION
  fonte STRING NOT NULL,         -- ptax | antt_ferrovia | conab | maritimo
  status STRING NOT NULL,        -- OK | FALHA
  etapa_falha STRING,            -- "n:modulo" da primeira etapa com erro
  codigo_saida INT64,
  inicio TIMESTAMP NOT NULL,
  fim TIMESTAMP,
  duracao_s FLOAT64,
  revisao STRING,                -- commit da imagem
  registrado_em TIMESTAMP
)
PARTITION BY DATE(inicio)
CLUSTER BY fonte
OPTIONS (partition_expiration_days = 400,
         description = "Saúde das coletas do nivon-coletor; execução != frescor do dado");
