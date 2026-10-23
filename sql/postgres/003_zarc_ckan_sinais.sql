-- NIVON - Histórico persistente das OBSERVAÇÕES CKAN do MAPA ZARC.
-- Execução inicial somente em projeto agrícola NIVON-AGRO-DADOS.
-- Revision ID CKAN NÃO É SHA do CSV; nunca promover a ZARC efetivo.
-- Colunas *_modified_text preservam horário sem timezone, como fornecido pela fonte.
CREATE TABLE IF NOT EXISTS nivon_agro_staging.zarc_ckan_sinais (
    resource_id text NOT NULL
      CHECK (resource_id='139e5a60-1f43-4cc8-aeab-a35dbbf816c0'),
    coletado_em timestamptz NOT NULL,
    metadata_fingerprint char(64) NOT NULL CHECK (metadata_fingerprint ~ '^[0-9a-f]{64}$'),
    licenca_declarada text NOT NULL CHECK (licenca_declarada IN ('cc-by','cc-by-3.0','cc-by-4.0')),
    pacote_revision_id text,
    recurso_revision_id text,
    pacote_modified_text text,
    recurso_modified_text text,
    fonte_registro text NOT NULL CHECK (fonte_registro='MAPA_CKAN_ZARC'),
    prova_url text NOT NULL,
    arquivo_sha256 char(64) DEFAULT NULL,
    csv_foi_baixado boolean NOT NULL DEFAULT FALSE CHECK (csv_foi_baixado = FALSE),
    publicavel_como_risco boolean NOT NULL DEFAULT FALSE CHECK (publicavel_como_risco = FALSE),
    PRIMARY KEY (resource_id,coletado_em),
    CHECK (arquivo_sha256 IS NULL)
);

CREATE INDEX IF NOT EXISTS idx_zarc_ckan_sinais_revision
  ON nivon_agro_staging.zarc_ckan_sinais(resource_id,metadata_fingerprint,coletado_em DESC);

-- Este snapshot de metadados pode ser armazenado antes dos dados agrícolas,
-- sem liberar o gate de coleta do CSV: enabled/collection_authorized seguem OFF.
