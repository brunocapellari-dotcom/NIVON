-- Motor de leitura: status por série P0. Nunca colapsar "fonte existe"
-- em "todas as séries atuais". Fonte Drive não alimenta este estado.
CREATE OR REPLACE VIEW public.nivon_p0_series_status_v AS
WITH expected(source,series_id,product,location) AS (
 VALUES
 ('CEPEA','soja_paranagua','soja','Paranaguá/PR'),
 ('CEPEA','soja_parana','soja','Paraná'),
 ('CEPEA','milho_esalq_b3','milho','Campinas/SP'),
 ('IMEA','soja_mt','soja','Mato Grosso'),
 ('IMEA','milho_mt','milho','Mato Grosso'),
 ('CONAB','soja_mt_safra','soja','Mato Grosso'),
 ('CONAB','milho_mt_safra','milho','Mato Grosso')
)
SELECT e.source,e.series_id,e.product,e.location,
 CASE WHEN e.source='CEPEA' THEN
  (SELECT max(reference_date) FROM public.nivon_cepea_prices q WHERE q.series_id=e.series_id)
 WHEN e.source='CONAB' THEN
  (SELECT max(published_on) FROM public.nivon_conab_safras q WHERE q.product=e.product AND q.uf='MT')
 ELSE NULL END AS last_reference_date,
 CASE WHEN s.auth_state='PENDING_WRITTEN_PERMISSION' THEN 'BLOCKED_RIGHTS'
 WHEN e.source='CEPEA' AND NOT EXISTS(SELECT 1 FROM public.nivon_cepea_prices q WHERE q.series_id=e.series_id) THEN 'NOT_INTEGRATED'
 WHEN e.source='CONAB' AND NOT EXISTS(SELECT 1 FROM public.nivon_conab_safras q WHERE q.product=e.product AND q.uf='MT') THEN 'NOT_INTEGRATED'
 WHEN (SELECT status FROM public.nivon_p0_source_checks c WHERE c.source=e.source ORDER BY c.id DESC LIMIT 1)='ERROR' THEN 'COLLECTOR_ERROR'
 WHEN e.source='CEPEA' AND (SELECT max(reference_date) FROM public.nivon_cepea_prices q WHERE q.series_id=e.series_id)<current_date-4 THEN 'SOURCE_LAG'
 WHEN e.source='CONAB' AND (SELECT max(published_on) FROM public.nivon_conab_safras q WHERE q.product=e.product AND q.uf='MT')<current_date-45 THEN 'SOURCE_LAG'
 WHEN s.ingest_state!='ACTIVE' THEN 'DATA_PRESENT_AUTOMATION_PENDING'
 ELSE 'CURRENT_AND_ACTIVE' END AS operational_status
FROM expected e JOIN public.nivon_p0_sources s ON s.source=e.source;
