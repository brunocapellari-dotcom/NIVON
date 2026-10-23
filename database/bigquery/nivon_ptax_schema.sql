-- NIVON PTAX: tabela de destino BigQuery para migracao DE CÓPIA do Neon.
-- Somente DDL TEMPLATE. Nao executar sem gate de projeto, billing, licença e backup.
-- Nao substituir dados nem interromper o Neon. RAW OData não está disponível nesta tabela.
-- Quote ID deterministico: SHA256 de moeda, referencia, horario original, tipo, compra, venda.
-- BigQuery nao garante UNIQUE; deduplicar/validar no pipeline.
CREATE TABLE IF NOT EXISTS `${PROJECT_ID}.nivon_core.ptax_quotes` (
  quote_id STRING NOT NULL OPTIONS(description="SHA256 da chave de negocio, nao do RAW OData"),
  currency STRING NOT NULL,
  reference_date DATE NOT NULL,
  quote_time_original STRING NOT NULL OPTIONS(description="Horario fornecido na API, preservado sem timezone inventado"),
  bulletin_type STRING NOT NULL OPTIONS(description="Valor original Neon, USD pode usar categoria tecnica"),
  buy_brl NUMERIC NOT NULL,
  sell_brl NUMERIC NOT NULL,
  unit STRING NOT NULL,
  source STRING NOT NULL,
  license STRING NOT NULL,
  published_at TIMESTAMP OPTIONS(description="NULL enquanto fonte nao fornece data de publicacao"),
  first_collected_at TIMESTAMP NOT NULL,
  last_verified_at TIMESTAMP NOT NULL,
  observation_kind STRING NOT NULL,
  record_sha256 STRING NOT NULL OPTIONS(description="SHA256 de representacao canonica de registro exportado, NAO checksum de payload original"),
  origem_sha256 STRING OPTIONS(description="SHA256 do payload bruto se houver evidencia; caso contrario NULL"),
  vintage_id STRING NOT NULL OPTIONS(description="Identidade da cotacao/revisao, consistente com a chave de deduplicacao do Neon"),
  source_neon_row_id INT64 OPTIONS(description="Chave surrogate de origem somente para conciliacao, nao chave de negocio"),
  migration_schema_version STRING NOT NULL,
  quality_status STRING NOT NULL
)
PARTITION BY reference_date
CLUSTER BY currency, bulletin_type
OPTIONS (
  require_partition_filter = TRUE,
  description = "Copia historica versionada de PTAX BCB USD/EUR de Neon; nao considerar completa nem atual sem auditoria."
);
