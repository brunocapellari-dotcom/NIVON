-- Evidência de arquivo público RAW copiado e lido de volta em pasta privada Google Drive.
-- Isto não equivale a bucket Neon nem backup independente em dois provedores.
CREATE TABLE IF NOT EXISTS nivon_agro_staging.zarc_drive_arquivos (
  source_sha256 char(64) PRIMARY KEY CHECK (source_sha256 ~ '^[0-9a-f]{64}$'),
  drive_file_id text NOT NULL,
  drive_folder_id text NOT NULL,
  drive_file_name text NOT NULL,
  zip_sha256 char(64) NOT NULL CHECK (zip_sha256 ~ '^[0-9a-f]{64}$'),
  zip_bytes bigint NOT NULL CHECK (zip_bytes > 0),
  raw_csv_sha256 char(64) NOT NULL CHECK (raw_csv_sha256=source_sha256),
  raw_csv_bytes bigint NOT NULL CHECK (raw_csv_bytes BETWEEN 1 AND 230000000),
  raw_gzip_sha256 char(64) NOT NULL CHECK (raw_gzip_sha256 ~ '^[0-9a-f]{64}$'),
  mt_jsonl_gzip_sha256 char(64) NOT NULL CHECK (mt_jsonl_gzip_sha256 ~ '^[0-9a-f]{64}$'),
  mt_rows integer NOT NULL CHECK (mt_rows>0),
  mt_municipalities integer NOT NULL CHECK (mt_municipalities>0),
  copy_downloaded_sha_verified boolean NOT NULL CHECK (copy_downloaded_sha_verified=true),
  local_raw_decompressed_sha_verified boolean NOT NULL CHECK (local_raw_decompressed_sha_verified=true),
  cloud_provider text NOT NULL DEFAULT 'GOOGLE_DRIVE' CHECK (cloud_provider='GOOGLE_DRIVE'),
  isolated_neon_bucket_backup boolean NOT NULL DEFAULT false CHECK (isolated_neon_bucket_backup=false),
  license_id text NOT NULL CHECK (license_id='cc-by'),
  attribution text NOT NULL,
  created_at timestamptz NOT NULL DEFAULT now(),
  evidence_status text NOT NULL DEFAULT 'DRIVE_COPY_READBACK_VERIFIED' CHECK(evidence_status='DRIVE_COPY_READBACK_VERIFIED'),
  publicavel boolean NOT NULL DEFAULT false CHECK(publicavel=false)
);
