-- CONAB: balanços oficiais de oferta/demanda por período e edição.
-- Métricas em mil toneladas; valores negativos publicados preservados.
CREATE TABLE IF NOT EXISTS public.nivon_conab_balancos (
 id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
 product TEXT NOT NULL CHECK(product IN ('soja','milho')),
 crop_period TEXT NOT NULL,
 publication_crop_year TEXT NOT NULL,
 publication_survey SMALLINT NOT NULL CHECK(publication_survey BETWEEN 1 AND 12),
 publication_date DATE NOT NULL,
 source_url TEXT NOT NULL,
 first_collected_at TIMESTAMPTZ NOT NULL DEFAULT now(),
 collected_at TIMESTAMPTZ NOT NULL DEFAULT now(),
 unit TEXT NOT NULL DEFAULT 'mil_ton' CHECK(unit='mil_ton'),
 initial_stock_mil_t NUMERIC(20,5),
 production_mil_t NUMERIC(20,5),
 import_mil_t NUMERIC(20,5),
 supply_mil_t NUMERIC(20,5),
 consumption_mil_t NUMERIC(20,5),
 export_mil_t NUMERIC(20,5),
 total_demand_mil_t NUMERIC(20,5),
 final_stock_mil_t NUMERIC(20,5),
 quality_warnings TEXT[] NOT NULL DEFAULT '{}',
 parser_version TEXT NOT NULL,
 epistemic_type TEXT NOT NULL DEFAULT 'INFORMADO',
 source_name TEXT NOT NULL DEFAULT 'CONAB',
 source_key TEXT NOT NULL,
 version_hash TEXT NOT NULL,
 UNIQUE(source_key,version_hash)
);
CREATE INDEX IF NOT EXISTS idx_nivon_conab_balancos_recent
 ON public.nivon_conab_balancos(product,crop_period,publication_date DESC);
