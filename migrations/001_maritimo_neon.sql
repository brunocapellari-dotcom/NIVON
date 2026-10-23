-- NIVON: modulo maritimo, migracao aditiva 001
-- Aplicada em 22/10/2026 ao banco NIVON (Neon, schema isolado).
CREATE SCHEMA IF NOT EXISTS nivon_maritimo;
CREATE TABLE IF NOT EXISTS nivon_maritimo.capturas (
 fonte TEXT NOT NULL, hash_conteudo CHAR(64) NOT NULL,
 primeiro_visto TIMESTAMPTZ NOT NULL, ultimo_visto TIMESTAMPTZ NOT NULL,
 registros INTEGER NOT NULL CHECK (registros >= 0),
 qualidade JSONB NOT NULL DEFAULT '{}'::jsonb,
 PRIMARY KEY (fonte, hash_conteudo));
CREATE TABLE IF NOT EXISTS nivon_maritimo.escalas_revisoes (
 fonte TEXT NOT NULL, escala_id TEXT NOT NULL, revisao_sha256 CHAR(64) NOT NULL,
 coletado_em TIMESTAMPTZ NOT NULL, natureza TEXT NOT NULL,
 situacao TEXT, publicavel BOOLEAN NOT NULL DEFAULT FALSE,
 payload JSONB NOT NULL,
 PRIMARY KEY (fonte, escala_id, revisao_sha256));
CREATE TABLE IF NOT EXISTS nivon_maritimo.fluxos_passagens (
 fonte TEXT NOT NULL DEFAULT 'FMI_PORTWATCH', passagem TEXT NOT NULL,
 data_referencia DATE NOT NULL, revisao_sha256 CHAR(64) NOT NULL,
 coletado_em TIMESTAMPTZ NOT NULL, transitos_ais INTEGER NOT NULL CHECK (transitos_ais >= 0),
 capacidade_proxy NUMERIC, payload JSONB NOT NULL,
 PRIMARY KEY (fonte, passagem, data_referencia, revisao_sha256));
CREATE INDEX IF NOT EXISTS idx_nivon_maritimo_escalas_vistas
 ON nivon_maritimo.escalas_revisoes(fonte,escala_id,coletado_em DESC);
CREATE INDEX IF NOT EXISTS idx_nivon_maritimo_passagens_data
 ON nivon_maritimo.fluxos_passagens(passagem,data_referencia DESC);
