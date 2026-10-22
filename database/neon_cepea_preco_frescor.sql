-- CEPEA: preços físicos primários da soja (Paranaguá, Paraná) e milho.
-- Um registro por versão da cotação, sempre com data de referência e origem.
CREATE TABLE IF NOT EXISTS public.nivon_cepea_prices(
 id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
 source TEXT NOT NULL DEFAULT 'CEPEA' CHECK(source='CEPEA'),
 series_id TEXT NOT NULL CHECK(series_id IN ('soja_paranagua','soja_parana','milho_esalq_b3')),
 product TEXT NOT NULL CHECK(product IN ('soja','milho')),
 location TEXT NOT NULL,
 unit TEXT NOT NULL DEFAULT 'BRL/sc60kg',
 reference_date DATE NOT NULL,
 published_at TIMESTAMPTZ,
 collected_at TIMESTAMPTZ NOT NULL,
 price_brl NUMERIC(18,6) NOT NULL CHECK(price_brl>0),
 source_url TEXT NOT NULL,
 license TEXT NOT NULL DEFAULT 'CC BY-NC 4.0',
 epistemic_type TEXT NOT NULL DEFAULT 'INFORMADO',
 quality_status TEXT NOT NULL DEFAULT 'VALIDADO',
 source_key TEXT NOT NULL,
 version_hash TEXT NOT NULL,
 UNIQUE(source_key,version_hash)
);
CREATE INDEX IF NOT EXISTS idx_nivon_cepea_precos_date
 ON public.nivon_cepea_prices(series_id,reference_date DESC);
-- O Drive é apenas referência; frescor deriva do dado oficial e da data de referência.
CREATE OR REPLACE VIEW public.nivon_p0_frescor AS
 SELECT s.source,s.ingest_state,s.auth_state,s.allow_automated_ingest,
  CASE WHEN s.source='CONAB' THEN (SELECT max(published_on) FROM public.nivon_conab_safras)
       WHEN s.source='CEPEA' THEN (SELECT max(reference_date) FROM public.nivon_cepea_prices)
       ELSE s.last_reference_on END AS latest_reference,
  s.last_checked_at,s.last_success_at,
  (SELECT count(*) FROM public.nivon_p0_drive_inventory d WHERE d.source=s.source) AS drive_archive_files,
  CASE WHEN s.auth_state='PENDING_WRITTEN_PERMISSION' OR s.ingest_state='BLOCKED_BY_RIGHTS' THEN 'BLOCKED_RIGHTS'
       WHEN s.source='CEPEA' AND (SELECT max(reference_date) FROM public.nivon_cepea_prices) IS NULL THEN 'NO_LIVE_DATA'
       WHEN s.source='CONAB' AND (SELECT max(published_on) FROM public.nivon_conab_safras) IS NULL THEN 'NO_LIVE_DATA'
       WHEN (SELECT status FROM public.nivon_p0_source_checks c WHERE c.source=s.source ORDER BY c.id DESC LIMIT 1)='ERROR' THEN 'COLLECTOR_ERROR'
       WHEN s.source='CEPEA' AND (SELECT max(reference_date) FROM public.nivon_cepea_prices)<current_date-4 THEN 'SOURCE_LAG'
       WHEN s.source='CONAB' AND (SELECT max(published_on) FROM public.nivon_conab_safras)<current_date-45 THEN 'SOURCE_LAG'
       WHEN NOT s.allow_automated_ingest OR s.ingest_state!='ACTIVE' THEN 'DATA_PRESENT_AUTOMATION_PENDING'
       ELSE 'CURRENT_AND_ACTIVE' END AS operational_status
 FROM public.nivon_p0_sources s;
