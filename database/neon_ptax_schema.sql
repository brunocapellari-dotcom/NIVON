-- NIVON / PTAX BCB — esquema não destrutivo do banco operacional Neon.
-- Idempotente; somente objetos próprios do NIVON. Sem dados ou credenciais.
CREATE TABLE IF NOT EXISTS public.nivon_ptax_quotes (
  id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  currency CHAR(3) NOT NULL CHECK (currency IN ('USD','EUR')),
  reference_date DATE NOT NULL,
  quote_time_original TEXT NOT NULL,
  bulletin_type TEXT NOT NULL,
  buy_brl NUMERIC(18,9) NOT NULL CHECK (buy_brl > 0),
  sell_brl NUMERIC(18,9) NOT NULL CHECK (sell_brl > 0),
  unit TEXT NOT NULL,
  source TEXT NOT NULL DEFAULT 'Banco Central do Brasil / PTAX',
  license TEXT NOT NULL DEFAULT 'ODbL',
  published_at TIMESTAMPTZ NULL,
  first_collected_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  last_verified_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  observation_kind TEXT NOT NULL DEFAULT 'INFORMADO',
  UNIQUE (currency,reference_date,quote_time_original,bulletin_type,buy_brl,sell_brl)
);
CREATE INDEX IF NOT EXISTS idx_nivon_ptax_quotes_latest
  ON public.nivon_ptax_quotes(currency,reference_date DESC,quote_time_original DESC);

CREATE TABLE IF NOT EXISTS public.nivon_ptax_runs (
  id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  job_type TEXT NOT NULL CHECK (job_type IN ('DAILY','BACKFILL','SMOKE')),
  currency CHAR(3) NOT NULL CHECK (currency IN ('USD','EUR')),
  window_start DATE NOT NULL,
  window_end DATE NOT NULL,
  started_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  finished_at TIMESTAMPTZ,
  status TEXT NOT NULL CHECK (status IN ('RUNNING','SUCCESS','EMPTY','ERROR')),
  fetched INTEGER NOT NULL DEFAULT 0 CHECK (fetched >= 0),
  inserted INTEGER NOT NULL DEFAULT 0 CHECK (inserted >= 0),
  error_class TEXT,
  detail TEXT,
  CHECK (window_end >= window_start)
);
CREATE INDEX IF NOT EXISTS idx_nivon_ptax_runs_by_date
  ON public.nivon_ptax_runs(currency,window_start,window_end,started_at DESC);

CREATE TABLE IF NOT EXISTS public.nivon_ptax_checkpoints (
  currency CHAR(3) NOT NULL CHECK (currency IN ('USD','EUR')),
  window_start DATE NOT NULL,
  window_end DATE NOT NULL,
  last_completed_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  status TEXT NOT NULL CHECK (status IN ('SUCCESS','EMPTY')),
  fetched INTEGER NOT NULL DEFAULT 0 CHECK(fetched >= 0),
  PRIMARY KEY (currency,window_start,window_end)
);
CREATE INDEX IF NOT EXISTS idx_nivon_ptax_checkpoints_latest
  ON public.nivon_ptax_checkpoints(currency,window_start DESC);
