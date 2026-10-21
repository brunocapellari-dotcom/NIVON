-- NIVON / CONAB — observacoes de safra e trilha de auditoria.
-- Nao inclui credenciais nem dados reais. Carga so de CONAB primaria validada.
CREATE TABLE IF NOT EXISTS public.nivon_conab_safras (
 id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
 product TEXT NOT NULL,
 uf CHAR(2) NOT NULL CHECK(uf ~ '^[A-Z]{2}$'),
 crop_year TEXT NOT NULL CHECK(crop_year ~ '^20[0-9]{2}/[0-9]{2}$'),
 survey_number SMALLINT CHECK(survey_number BETWEEN 1 AND 12),
 published_on DATE,
 reference_date DATE,
 collected_at TIMESTAMPTZ NOT NULL DEFAULT now(),
 competence TEXT NOT NULL,
 area_mil_ha NUMERIC(18,4) CHECK(area_mil_ha>=0),
 yield_kg_ha NUMERIC(18,4) CHECK(yield_kg_ha>=0),
 production_mil_t NUMERIC(18,4) CHECK(production_mil_t>=0),
 source_name TEXT NOT NULL DEFAULT 'CONAB',
 source_uri TEXT,
 source_sha256 TEXT,
 parser_version TEXT NOT NULL,
 epistemic_type TEXT NOT NULL DEFAULT 'PROJETADO'
  CHECK(epistemic_type IN ('OBSERVADO','INFORMADO','PROJETADO','ESTIMADO','INFERIDO')),
 origin_kind TEXT NOT NULL DEFAULT 'conab.safras',
 source_key TEXT NOT NULL,
 version_hash TEXT NOT NULL,
 quality_status TEXT NOT NULL DEFAULT 'VALIDADO',
 UNIQUE(source_key,version_hash),
 CHECK(area_mil_ha IS NOT NULL OR yield_kg_ha IS NOT NULL OR production_mil_t IS NOT NULL)
);
CREATE INDEX IF NOT EXISTS idx_nivon_conab_safras_crop
  ON public.nivon_conab_safras(product,uf,crop_year,survey_number,published_on DESC);
CREATE TABLE IF NOT EXISTS public.nivon_conab_ingestions (
 id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
 source_name TEXT NOT NULL DEFAULT 'CONAB',
 dataset TEXT NOT NULL,
 product TEXT, uf TEXT, crop_year TEXT, survey_number SMALLINT,
 collection_started_at TIMESTAMPTZ NOT NULL DEFAULT now(),
 collection_finished_at TIMESTAMPTZ,
 status TEXT NOT NULL CHECK(status IN ('STARTED','SUCCESS','EMPTY','FAILED','QUARANTINED')),
 rows_received INTEGER NOT NULL DEFAULT 0,
 rows_validated INTEGER NOT NULL DEFAULT 0,
 rows_inserted INTEGER NOT NULL DEFAULT 0,
 source_uri TEXT, error_code TEXT,
 CHECK(rows_received>=0 AND rows_validated>=0 AND rows_inserted>=0)
);
CREATE INDEX IF NOT EXISTS idx_nivon_conab_ingestions_recent
  ON public.nivon_conab_ingestions(dataset,collection_started_at DESC);
