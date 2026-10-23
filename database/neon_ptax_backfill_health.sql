-- NIVON PTAX: auditoria read-only do backfill sem inferir cobertura diária.
-- Espelha a função operacional: START=2020-01-01; janela de 31 dias;
-- hoje na zona America/Sao_Paulo, independente de fuso do servidor.
-- Janelas DAILY são separadas e não significam histórico completo.
WITH params AS (
  SELECT DATE '2020-01-01' AS first_date,
         (now() AT TIME ZONE 'America/Sao_Paulo')::date AS as_of_date
), ccy(currency) AS (
  VALUES ('USD'::text), ('EUR'::text)
), expected AS (
  SELECT c.currency,
    (p.first_date + (g.n * 31))::date AS window_start,
    LEAST(p.first_date + g.n * 31 + 30, p.as_of_date)::date AS window_end
  FROM params p CROSS JOIN ccy c
  CROSS JOIN LATERAL generate_series(
    0, (p.as_of_date - p.first_date) / 31
  ) AS g(n)
), checked AS (
  SELECT e.currency, e.window_start, e.window_end,
         cp.status AS checkpoint_status, cp.fetched,
         cp.last_completed_at
  FROM expected e
  LEFT JOIN public.nivon_ptax_checkpoints cp
  ON cp.currency=e.currency AND cp.window_start=e.window_start
   AND cp.window_end=e.window_end
), summary AS (
  SELECT currency,
    COUNT(*)::int AS expected_windows,
    COUNT(*) FILTER (WHERE checkpoint_status IN ('SUCCESS','EMPTY'))::int AS completed_windows,
    COUNT(*) FILTER (WHERE checkpoint_status IS NULL)::int AS pending_windows,
    MIN(window_start) FILTER (WHERE checkpoint_status IS NULL) AS next_start,
    MAX(window_end) FILTER (WHERE checkpoint_status IN ('SUCCESS','EMPTY')) AS farthest_completed_end,
    MAX(last_completed_at) AS last_checkpoint,
    SUM(fetched) FILTER (WHERE checkpoint_status IN ('SUCCESS','EMPTY'))::bigint AS fetched_completed
  FROM checked
  GROUP BY currency
), off_grid AS (
  SELECT cp.currency,
    COUNT(*)::int AS other_checkpoint_windows
  FROM public.nivon_ptax_checkpoints cp
  WHERE NOT EXISTS (
    SELECT 1 FROM expected e
    WHERE e.currency=cp.currency AND e.window_start=cp.window_start
      AND e.window_end=cp.window_end
  )
  GROUP BY cp.currency
), runs AS (
  SELECT currency,
    COUNT(*) FILTER (WHERE job_type='BACKFILL' AND status='ERROR')::int AS backfill_errors,
    COUNT(*) FILTER (WHERE job_type='DAILY' AND status='ERROR')::int AS daily_errors,
    MAX(finished_at) FILTER (WHERE job_type='BACKFILL' AND status IN ('SUCCESS','EMPTY')) AS last_backfill_run,
    MAX(finished_at) FILTER (WHERE job_type='DAILY' AND status IN ('SUCCESS','EMPTY')) AS last_daily_run
  FROM public.nivon_ptax_runs GROUP BY currency
), observations AS (
  SELECT currency,COUNT(*)::int AS stored_quotes,
    COUNT(DISTINCT reference_date)::int AS stored_reference_dates,
    MAX(reference_date) AS newest_observed_date
  FROM public.nivon_ptax_quotes GROUP BY currency
), payload AS (
 SELECT
  s.currency,s.expected_windows,s.completed_windows,s.pending_windows,
  COALESCE(o.other_checkpoint_windows,0) AS non_historical_checkpoints,
  CASE WHEN s.next_start IS NOT NULL THEN
    s.next_start - 1 ELSE p.as_of_date END AS contiguous_completed_through,
  s.next_start AS next_pending_start,
  CASE WHEN s.next_start IS NULL THEN NULL
    ELSE LEAST(s.next_start + 30,p.as_of_date) END AS next_pending_end,
  s.farthest_completed_end,
  s.last_checkpoint,
  COALESCE(s.fetched_completed,0) AS backfill_fetched,
  COALESCE(r.backfill_errors,0) AS backfill_errors,
  COALESCE(r.daily_errors,0) AS daily_errors,
  r.last_backfill_run,r.last_daily_run,
  COALESCE(b.stored_quotes,0) AS stored_quotes,
  COALESCE(b.stored_reference_dates,0) AS stored_reference_dates,
  b.newest_observed_date,
  -- Completude por janela NAO e completude diaria, nem prova de fonte.
  false AS historical_source_coverage_verified,
  false AS gcp_migration_authorized
 FROM summary s CROSS JOIN params p
 LEFT JOIN off_grid o ON o.currency=s.currency
 LEFT JOIN runs r ON r.currency=s.currency
 LEFT JOIN observations b ON b.currency=s.currency
)
SELECT jsonb_build_object(
 'contract','NIVON_PTAX_BACKFILL_HEALTH_V1',
 'observed_at_utc',TO_CHAR(statement_timestamp() AT TIME ZONE 'UTC','YYYY-MM-DD"T"HH24:MI:SS"Z"'),
 'as_of_sao_paulo_date',(SELECT as_of_date FROM params),
 'historical_start',(SELECT first_date FROM params),
 'nominal_window_days',31,
 'status','OBSERVED_CHECKPOINTS_NOT_FULL_SOURCE_COVERAGE',
 'by_currency',(
  SELECT jsonb_agg(to_jsonb(payload) ORDER BY currency) FROM payload
 ),
 'external_backup_verified',false,
 'bigquery_loaded',false,
 'cutover_approved',false
) AS backfill_health;