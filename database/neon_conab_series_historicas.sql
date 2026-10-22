-- Dados históricos CONAB por safra (diferentes dos levantamentos mensais).
-- Nenhuma publicação diária é inferida; uso de fonte primária conab_serie_historica.
CREATE TABLE IF NOT EXISTS public.nivon_conab_series_historicas (
 id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
 product TEXT NOT NULL CHECK(product IN ('soja','milho')),
 uf CHAR(2) NOT NULL CHECK(uf='MT'),
 crop_year TEXT NOT NULL CHECK(crop_year ~ '^20[0-9]{2}/[0-9]{2}$'),
 region TEXT,
 area_planted_mil_ha NUMERIC(18,6),
 area_producing_mil_ha NUMERIC(18,6),
 area_formation_mil_ha NUMERIC(18,6),
 area_harvested_mil_ha NUMERIC(18,6),
 production_mil_t NUMERIC(18,6),
 productivity_kg_ha NUMERIC(18,6),
 published_on DATE NULL,
 reference_date DATE NULL,
 competence TEXT NOT NULL,
 collected_at TIMESTAMPTZ NOT NULL,
 source_name TEXT NOT NULL DEFAULT 'CONAB',
 origin_kind TEXT NOT NULL DEFAULT 'conab_serie_historica',
 source_uri TEXT NOT NULL,
 parser_version TEXT NOT NULL,
 epistemic_type TEXT NOT NULL DEFAULT 'INFORMADO',
 source_key TEXT NOT NULL, version_hash TEXT NOT NULL,
 quality_status TEXT NOT NULL DEFAULT 'VALIDADO',
 UNIQUE(source_key,version_hash),
 CHECK (area_planted_mil_ha IS NOT NULL OR production_mil_t IS NOT NULL OR productivity_kg_ha IS NOT NULL)
);
CREATE INDEX IF NOT EXISTS idx_nivon_conab_historico
 ON public.nivon_conab_series_historicas(product,uf,crop_year DESC);
