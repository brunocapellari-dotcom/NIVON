-- NIVON PTAX: evidência agregada e read-only antes de exportação/migração.
-- Sem valores de preços, identificadores pessoais, credenciais ou mutações.
-- Dados de execuções e janela histórica NÃO provam disponibilidade de todos os pregões.
WITH quote_summary AS (
  SELECT
    COUNT(*)::bigint AS quotes,
    COUNT(*) FILTER (WHERE first_collected_at > last_verified_at)::bigint AS invalid_timestamps,
    COUNT(*) FILTER (WHERE currency NOT IN ('USD','EUR'))::bigint AS invalid_currency,
    COUNT(*) FILTER (WHERE buy_brl <= 0 OR sell_brl <= 0)::bigint AS invalid_prices,
    COUNT(*) FILTER (WHERE published_at IS NOT NULL AND published_at > last_verified_at)::bigint AS suspect_publication,
    (COUNT(*) - COUNT(DISTINCT (currency,reference_date,quote_time_original,bulletin_type,buy_brl,sell_brl)))::bigint AS duplicate_business_keys
  FROM public.nivon_ptax_quotes
),
currency_summary AS (
  SELECT currency, COUNT(*)::bigint AS quotes,
     COUNT(DISTINCT reference_date)::bigint AS reference_days,
     MIN(reference_date) AS first_reference,
     MAX(reference_date) AS last_reference,
     MAX(last_verified_at) AS last_verified
  FROM public.nivon_ptax_quotes
  GROUP BY currency
),
year_summary AS (
  SELECT currency, EXTRACT(YEAR FROM reference_date)::int AS reference_year,
     COUNT(*)::bigint AS quotes, COUNT(DISTINCT reference_date)::bigint AS reference_days
  FROM public.nivon_ptax_quotes
  GROUP BY currency, EXTRACT(YEAR FROM reference_date)
),
run_summary AS (
  SELECT COUNT(*)::bigint AS runs,
     COUNT(*) FILTER (WHERE status='ERROR')::bigint AS error_runs,
     COUNT(*) FILTER (WHERE status='RUNNING')::bigint AS running_runs,
     COUNT(*) FILTER (WHERE status='SUCCESS')::bigint AS successful_runs
  FROM public.nivon_ptax_runs
),
checkpoint_summary AS (
  SELECT COUNT(*)::bigint AS checkpoints FROM public.nivon_ptax_checkpoints
)
SELECT jsonb_build_object(
  'contract', 'NIVON_PTAX_SOURCE_AUDIT_V1',
  'snapshot_timestamp_utc', TO_CHAR(statement_timestamp() AT TIME ZONE 'UTC','YYYY-MM-DD"T"HH24:MI:SS"Z"'),
  'source', 'Neon NIVON-PTAX-OPERACIONAL/public.nivon_ptax_quotes',
  'quote_count', (SELECT quotes FROM quote_summary),
  'run_count', (SELECT runs FROM run_summary),
  'run_errors', (SELECT error_runs FROM run_summary),
  'run_running', (SELECT running_runs FROM run_summary),
  'run_successful', (SELECT successful_runs FROM run_summary),
  'checkpoint_count', (SELECT checkpoints FROM checkpoint_summary),
  'invalid_timestamps', (SELECT invalid_timestamps FROM quote_summary),
  'invalid_currency', (SELECT invalid_currency FROM quote_summary),
  'invalid_prices', (SELECT invalid_prices FROM quote_summary),
  'suspect_publication', (SELECT suspect_publication FROM quote_summary),
  'duplicate_business_keys', (SELECT duplicate_business_keys FROM quote_summary),
  'by_currency', COALESCE((
    SELECT jsonb_agg(jsonb_build_object(
      'currency',currency,'quotes',quotes,'reference_days',reference_days,
      'first_reference',first_reference,'last_reference',last_reference,
      'last_verified',last_verified
    ) ORDER BY currency) FROM currency_summary
  ),'[]'::jsonb),
  'by_year', COALESCE((
    SELECT jsonb_agg(jsonb_build_object(
      'currency',currency,'year',reference_year,'quotes',quotes,'reference_days',reference_days
    ) ORDER BY currency, reference_year) FROM year_summary
  ),'[]'::jsonb),
  'origin_coverage_complete', false,
  'external_backup_restored', false,
  'bigquery_migrated', false,
  'migration_authorized', false
) AS source_audit_manifest;
