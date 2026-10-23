-- IMEA: licença declarada pelo proprietário do NIVON, não verificada com provedor.
-- Staging nunca substitui data_publicacao por data_referencia.
CREATE TABLE IF NOT EXISTS public.nivon_imea_access_attestations(
 id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
 attested_at TIMESTAMPTZ NOT NULL DEFAULT now(),
 attested_by TEXT NOT NULL, attestation TEXT NOT NULL,
 coverage TEXT NOT NULL,
 provider_document_verified BOOLEAN NOT NULL DEFAULT FALSE,
 provider_authorization_uri TEXT,
 operational_scope TEXT NOT NULL DEFAULT 'PILOT_PUBLIC_PRICES',
 notes TEXT
);
CREATE TABLE IF NOT EXISTS public.nivon_imea_prices_staging (
 id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
 chain TEXT NOT NULL CHECK(chain IN ('soja','milho','algodao','bovinocultura')),
 indicator_id TEXT NOT NULL,
 indicator_name TEXT NOT NULL,
 location TEXT NOT NULL,
 unit TEXT NOT NULL,
 crop_year TEXT,
 price NUMERIC(20,6) NOT NULL CHECK(price>0),
 published_at TIMESTAMP,
 reference_date DATE,
 source_url TEXT NOT NULL,
 source_name TEXT NOT NULL DEFAULT 'IMEA',
 authorization_basis TEXT NOT NULL DEFAULT 'OWNER_ATTESTED',
 quality_status TEXT NOT NULL DEFAULT 'PUBLISHED_DATE_ONLY',
 first_collected_at TIMESTAMPTZ NOT NULL DEFAULT now(),
 last_seen_at TIMESTAMPTZ NOT NULL DEFAULT now(),
 source_key TEXT NOT NULL,
 version_hash TEXT NOT NULL,
 UNIQUE(source_key,version_hash),
 CHECK(reference_date IS NULL OR reference_date<=published_at::date)
);
CREATE INDEX IF NOT EXISTS idx_nivon_imea_publications
 ON public.nivon_imea_prices_staging(chain,indicator_id,location,published_at DESC);
-- Observação: o registro de atestação é inserido operacionalmente com a data real.
