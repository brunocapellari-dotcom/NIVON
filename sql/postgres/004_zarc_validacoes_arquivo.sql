-- NIVON ZARC: comprovantes de leitura integral, independentes dos dados brutos.
-- Uma leitura efetivamente validada NÃO significa RAW gravado no bucket nem
-- carga das linhas no Postgres. Imutável por ID da execução.
CREATE TABLE IF NOT EXISTS nivon_agro_staging.zarc_validacoes_arquivo (
  run_github bigint PRIMARY KEY CHECK (run_github>0),
  origem text NOT NULL DEFAULT 'MAPA_ZARC' CHECK (origem='MAPA_ZARC'),
  dataset_id text NOT NULL DEFAULT 'ZARC_JANELAS' CHECK (dataset_id='ZARC_JANELAS'),
  collected_utc timestamptz NOT NULL,
  source_sha256 char(64) NOT NULL CHECK (source_sha256 ~ '^[0-9a-f]{64}$'),
  metadata_sha256 char(64) NOT NULL CHECK (metadata_sha256 ~ '^[0-9a-f]{64}$'),
  raw_bytes bigint NOT NULL CHECK (raw_bytes BETWEEN 1 AND 230000000),
  brazil_rows integer NOT NULL CHECK (brazil_rows>0),
  mt_rows integer NOT NULL CHECK (mt_rows>0),
  mt_municipalities integer NOT NULL CHECK (mt_municipalities BETWEEN 1 AND 1500),
  license_id text NOT NULL CHECK (license_id='cc-by'),
  attribution text NOT NULL,
  code_commit_sha char(40) NOT NULL CHECK (code_commit_sha ~ '^[0-9a-f]{40}$'),
  evidence_url text NOT NULL,
  local_ledger_raw_verified boolean NOT NULL CHECK (local_ledger_raw_verified=TRUE),
  sqlite_integrity_check text NOT NULL CHECK (sqlite_integrity_check='ok'),
  archived_to_private_bucket boolean NOT NULL DEFAULT FALSE CHECK(archived_to_private_bucket=FALSE),
  rows_loaded_to_agro_database boolean NOT NULL DEFAULT FALSE CHECK(rows_loaded_to_agro_database=FALSE),
  approved_for_publication boolean NOT NULL DEFAULT FALSE CHECK(approved_for_publication=FALSE),
  evidence_recorded_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_zarc_validacoes_sha_coleta
 ON nivon_agro_staging.zarc_validacoes_arquivo(source_sha256,collected_utc DESC);
