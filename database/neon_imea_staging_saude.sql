-- Painel observabilidade IMEA. Publicação não substitui data de referência.
CREATE OR REPLACE VIEW public.nivon_imea_staging_saude_v AS
WITH cad AS (SELECT 'soja'::text AS chain UNION ALL SELECT 'milho'::text),
 runs AS (SELECT MAX(checked_at) AS last_ingest_check FROM public.nivon_p0_source_checks
           WHERE source='IMEA' AND check_kind='OFFICIAL_STAGING' AND status IN ('OK','NO_UPDATE'))
SELECT c.chain, COUNT(p.id) AS records,
 COUNT(DISTINCT p.indicator_id) AS indicators,
 COUNT(p.id) FILTER(WHERE p.reference_date IS NULL) AS publication_only,
 MAX(p.published_at) AS latest_published_at,
 MAX(p.last_seen_at) AS latest_collected_at,
 CASE WHEN COUNT(p.id)=0 THEN 'SEM_DADOS'
      WHEN COUNT(p.id) FILTER(WHERE p.reference_date IS NOT NULL)=0
           THEN 'HISTORICO_PUBLICACAO_SEM_DATA_REFERENCIA'
      ELSE 'EXIGIR_HOMOLOGACAO_POR_SERIE' END AS use_class,
 CASE WHEN runs.last_ingest_check IS NULL THEN 'COLLECTOR_NOT_TESTED'
      WHEN runs.last_ingest_check<now()-interval '3 days' THEN 'COLLECTOR_LAG'
      ELSE 'COLLECTOR_RECENT' END AS collector_state
FROM cad c LEFT JOIN public.nivon_imea_prices_staging p ON p.chain=c.chain
CROSS JOIN runs
GROUP BY c.chain,runs.last_ingest_check;
