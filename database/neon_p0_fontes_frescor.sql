-- NIVON — priorização P0 e controle de atualização. Sem dados históricos promovidos.
CREATE TABLE IF NOT EXISTS public.nivon_p0_sources (
 source TEXT PRIMARY KEY CHECK(source IN ('CEPEA','IMEA','CONAB')),
 priority TEXT NOT NULL DEFAULT 'P0',
 use_class TEXT NOT NULL DEFAULT 'NONCOMMERCIAL',
 auth_state TEXT NOT NULL CHECK(auth_state IN ('CC_BY_NC','PENDING_WRITTEN_PERMISSION','PUBLIC_OFFICIAL_DATA')),
 ingest_state TEXT NOT NULL CHECK(ingest_state IN ('ACTIVE','READINESS_ONLY','BLOCKED_BY_RIGHTS','TESTED_NOT_SCHEDULED')),
 expected_cadence TEXT NOT NULL,
 allow_automated_ingest BOOLEAN NOT NULL DEFAULT FALSE,
 last_checked_at TIMESTAMPTZ,
 last_success_at TIMESTAMPTZ,
 last_reference_on DATE,
 freshness_state TEXT NOT NULL DEFAULT 'UNKNOWN',
 details TEXT,
 updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE TABLE IF NOT EXISTS public.nivon_p0_source_checks (
 id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
 source TEXT NOT NULL REFERENCES public.nivon_p0_sources(source),
 checked_at TIMESTAMPTZ NOT NULL DEFAULT now(),
 check_kind TEXT NOT NULL,
 status TEXT NOT NULL CHECK(status IN ('OK','NO_UPDATE','BLOCKED','SOURCE_LAG','ERROR','PENDING')),
 latest_reference_on DATE,
 inserted_rows INTEGER NOT NULL DEFAULT 0 CHECK(inserted_rows>=0),
 warning TEXT,
 provenance_uri TEXT,
 job_identifier TEXT
);
CREATE INDEX IF NOT EXISTS idx_nivon_p0_source_checks_recent
 ON public.nivon_p0_source_checks(source,checked_at DESC);
CREATE TABLE IF NOT EXISTS public.nivon_p0_drive_inventory (
 drive_file_id TEXT PRIMARY KEY,
 source TEXT NOT NULL REFERENCES public.nivon_p0_sources(source),
 filename TEXT NOT NULL,
 mime_type TEXT NOT NULL,
 file_bytes BIGINT,
 source_modified_at TIMESTAMPTZ,
 discovered_at TIMESTAMPTZ NOT NULL DEFAULT now(),
 last_scanned_at TIMESTAMPTZ NOT NULL DEFAULT now(),
 classification TEXT NOT NULL DEFAULT 'HISTORICAL_REFERENCE_ONLY'
 CHECK(classification IN ('HISTORICAL_REFERENCE_ONLY','AWAITING_SCHEMA','AUTHORIZED_IMPORT','REJECTED')),
 promoted_to_current BOOLEAN NOT NULL DEFAULT FALSE CHECK(promoted_to_current = FALSE),
 content_imported BOOLEAN NOT NULL DEFAULT FALSE,
 notes TEXT
);
INSERT INTO public.nivon_p0_sources
 (source,auth_state,ingest_state,expected_cadence,allow_automated_ingest,details)
 VALUES
 ('CEPEA','CC_BY_NC','READINESS_ONLY','business_daily',FALSE,'Direct official CEPEA indicator access must pass provenance and freshness before ingestion'),
 ('IMEA','PENDING_WRITTEN_PERMISSION','BLOCKED_BY_RIGHTS','business_daily_or_release',FALSE,'Requires documented permission for automated collection and retention'),
 ('CONAB','PUBLIC_OFFICIAL_DATA','TESTED_NOT_SCHEDULED','monthly_releases_and_weekly_safra',TRUE,'Live CONAB OIDC import proven; GitHub scheduled job awaits merge to default branch')
 ON CONFLICT(source) DO NOTHING;
-- Historical Drive metadata may be indexed separately but MUST NEVER make a source current.
