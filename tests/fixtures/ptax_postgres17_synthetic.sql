-- SOMENTE DADOS SINTETICOS. Nunca carregar contra Neon operacional.
CREATE TABLE public.nivon_ptax_quotes (
  id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  currency CHAR(3) NOT NULL CHECK (currency IN ('USD','EUR')),
  reference_date DATE NOT NULL,
  quote_time_original TEXT NOT NULL,
  bulletin_type TEXT NOT NULL,
  buy_brl NUMERIC(18,9) NOT NULL CHECK(buy_brl>0),
  sell_brl NUMERIC(18,9) NOT NULL CHECK(sell_brl>0),
  unit TEXT NOT NULL,
  source TEXT NOT NULL DEFAULT 'Banco Central do Brasil / PTAX',
  license TEXT NOT NULL DEFAULT 'ODbL',
  published_at TIMESTAMPTZ NULL,
  first_collected_at TIMESTAMPTZ NOT NULL,
  last_verified_at TIMESTAMPTZ NOT NULL,
  observation_kind TEXT NOT NULL DEFAULT 'INFORMADO',
  UNIQUE (currency,reference_date,quote_time_original,bulletin_type,buy_brl,sell_brl)
);
CREATE TABLE public.nivon_ptax_runs (
  id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  job_type TEXT NOT NULL CHECK(job_type IN ('DAILY','BACKFILL','SMOKE')),
  currency CHAR(3) NOT NULL CHECK(currency IN ('USD','EUR')),
  window_start DATE NOT NULL,
  window_end DATE NOT NULL,
  started_at TIMESTAMPTZ NOT NULL,
  finished_at TIMESTAMPTZ,
  status TEXT NOT NULL CHECK(status IN ('RUNNING','SUCCESS','EMPTY','ERROR')),
  fetched INTEGER NOT NULL DEFAULT 0,
  inserted INTEGER NOT NULL DEFAULT 0,
  error_class TEXT,
  detail TEXT,
  CHECK(window_end>=window_start)
);
CREATE TABLE public.nivon_ptax_checkpoints (
  currency CHAR(3) NOT NULL CHECK(currency IN ('USD','EUR')),
  window_start DATE NOT NULL,
  window_end DATE NOT NULL,
  last_completed_at TIMESTAMPTZ NOT NULL,
  status TEXT NOT NULL CHECK(status IN ('SUCCESS','EMPTY')),
  fetched INTEGER NOT NULL DEFAULT 0,
  PRIMARY KEY(currency,window_start,window_end)
);
INSERT INTO public.nivon_ptax_quotes
(currency,reference_date,quote_time_original,bulletin_type,buy_brl,sell_brl,unit,source,license,published_at,first_collected_at,last_verified_at,observation_kind)
VALUES
('USD','2026-10-21','2026-10-21 13:03:07','COTACAO_DOLAR_DIARIA',5.123456789,5.123456790,'BRL/USD','TESTE SINTETICO','TEST-ONLY',NULL,'2026-10-21 14:10:00+00','2026-10-21 15:10:00+00','INFORMADO'),
('EUR','2026-10-21','2026-10-21 13:11:00','FECHAMENTO',6.123456789,6.123456790,'BRL/EUR','TESTE SINTETICO','TEST-ONLY',NULL,'2026-10-21 14:11:00+00','2026-10-21 15:11:00+00','INFORMADO'),
('EUR','2026-10-21','2026-10-21 13:11:00','FECHAMENTO',6.123456788,6.123456790,'BRL/EUR','TESTE SINTETICO','TEST-ONLY',NULL,'2026-10-21 14:12:00+00','2026-10-21 15:12:00+00','INFORMADO');
INSERT INTO public.nivon_ptax_runs
(job_type,currency,window_start,window_end,started_at,finished_at,status,fetched,inserted,error_class,detail)
VALUES
('BACKFILL','USD','2026-10-01','2026-10-21','2026-10-21 14:00:00+00','2026-10-21 14:01:00+00','SUCCESS',1,1,NULL,NULL),
('BACKFILL','EUR','2026-10-01','2026-10-21','2026-10-21 14:00:00+00','2026-10-21 14:01:00+00','SUCCESS',2,2,NULL,NULL);
INSERT INTO public.nivon_ptax_checkpoints
(currency,window_start,window_end,last_completed_at,status,fetched)
VALUES
('USD','2026-10-01','2026-10-21','2026-10-21 14:01:00+00','SUCCESS',1),
('EUR','2026-10-01','2026-10-21','2026-10-21 14:01:00+00','SUCCESS',2);
