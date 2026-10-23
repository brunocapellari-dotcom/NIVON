-- NIVON: registro de saúde da ingestão, aditivo e idempotente.
CREATE TABLE IF NOT EXISTS nivon_maritimo.coleta_execucoes(
 run_id UUID NOT NULL,
 fonte TEXT NOT NULL,
 coletado_em TIMESTAMPTZ NOT NULL,
 estado TEXT NOT NULL CHECK (estado IN ('OK','QUARENTENA','FALHA')),
 quantidade INTEGER NOT NULL CHECK (quantidade>=0),
 revisoes INTEGER NOT NULL CHECK (revisoes>=0),
 captura_sha256 TEXT,
 motivo TEXT NOT NULL,
 duracao_ms INTEGER NOT NULL CHECK (duracao_ms>=0),
 PRIMARY KEY(run_id,fonte)
);
CREATE INDEX IF NOT EXISTS idx_nivon_maritimo_coletas_fonte_data
 ON nivon_maritimo.coleta_execucoes(fonte,coletado_em DESC);
