-- NIVON / ZARC MT — PostgreSQL 17 staging, MIGRACAO NAO EXECUTADA.
-- Uso futuro: somente banco agrícola NIVON selecionado formalmente.
-- NÃO executar no banco PTAX operacional por similaridade de nome.
-- Escopo: histórico por SHA de arquivo, linha física original e timestamps.
-- Não interpretar dec1..dec36 como riscos sem metodologia homologada.
-- RAW CSV integral fica em cofre de objetos com retenção/backup, não no Git.

BEGIN;
CREATE SCHEMA IF NOT EXISTS nivon_agro_staging;

CREATE TABLE IF NOT EXISTS nivon_agro_staging.zarc_edicoes (
    source_id text NOT NULL DEFAULT 'ZARC' CHECK (source_id = 'ZARC'),
    dataset_id text NOT NULL DEFAULT 'ZARC_JANELAS' CHECK (dataset_id = 'ZARC_JANELAS'),
    source_sha256 char(64) PRIMARY KEY
        CHECK (source_sha256 ~ '^[0-9a-f]{64}$'),
    competencia text NOT NULL CHECK (competencia = '2026/2027'),
    schema_version text NOT NULL CHECK (schema_version = 'ZARC_RAW_MT_V1'),
    raw_bytes bigint NOT NULL CHECK (raw_bytes BETWEEN 1 AND 230000000),
    total_linhas_brasil bigint NOT NULL CHECK (total_linhas_brasil > 0),
    linhas_mt bigint NOT NULL CHECK (linhas_mt > 0),
    municipios_mt integer NOT NULL CHECK (municipios_mt > 0),
    source_url text NOT NULL,
    data_referencia date,
    data_publicacao date,
    raw_object_sha256 char(64) NOT NULL CHECK (raw_object_sha256 = source_sha256),
    raw_backup_verificado boolean NOT NULL DEFAULT false,
    direitos_revisados boolean NOT NULL DEFAULT false,
    dados_agronomicos_homologados boolean NOT NULL DEFAULT false,
    apto_backtest boolean NOT NULL DEFAULT false,
    publicavel boolean NOT NULL DEFAULT false,
    criado_em timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT zarc_publicacao_condicionada CHECK (
        NOT publicavel OR (
            direitos_revisados AND dados_agronomicos_homologados
            AND raw_backup_verificado
        )
    ),
    CONSTRAINT zarc_backtest_condicionado CHECK (
        NOT apto_backtest OR data_publicacao IS NOT NULL
    )
);

CREATE TABLE IF NOT EXISTS nivon_agro_staging.zarc_coletas (
    source_sha256 char(64) NOT NULL
      REFERENCES nivon_agro_staging.zarc_edicoes(source_sha256),
    coletado_em timestamptz NOT NULL,
    tipo text NOT NULL CHECK (tipo IN ('SINTETICO','REAL_AUTORIZADO')),
    evidencia_direitos text,
    PRIMARY KEY (source_sha256, coletado_em),
    CONSTRAINT zarc_direitos_se_tipo_real CHECK (
      tipo <> 'REAL_AUTORIZADO' OR evidencia_direitos IS NOT NULL
    )
);

CREATE TABLE IF NOT EXISTS nivon_agro_staging.zarc_linhas_mt (
    source_sha256 char(64) NOT NULL
      REFERENCES nivon_agro_staging.zarc_edicoes(source_sha256),
    linha_fisica bigint NOT NULL CHECK (linha_fisica > 0),
    municipio_ibge char(7) NOT NULL CHECK (municipio_ibge ~ '^[0-9]{7}$'),
    municipio_sicor text,
    cultura_original text NOT NULL,
    cod_cultura text NOT NULL,
    cod_ciclo text NOT NULL,
    cod_solo text NOT NULL,
    cod_clima text NOT NULL,
    cod_manejo text NOT NULL,
    cod_nm text NOT NULL,
    portaria_original text NOT NULL,
    chave_logica_sha char(64) NOT NULL CHECK (chave_logica_sha ~ '^[0-9a-f]{64}$'),
    conteudo_sha char(64) NOT NULL CHECK (conteudo_sha ~ '^[0-9a-f]{64}$'),
    dados_raw jsonb NOT NULL CHECK (jsonb_typeof(dados_raw) = 'object'),
    risco_interpretado boolean NOT NULL DEFAULT false
      CHECK (risco_interpretado = false),
    PRIMARY KEY (source_sha256, linha_fisica)
);

CREATE INDEX IF NOT EXISTS idx_zarc_linhas_mt_municipio_cultura
    ON nivon_agro_staging.zarc_linhas_mt
        (municipio_ibge, cultura_original, source_sha256);
CREATE INDEX IF NOT EXISTS idx_zarc_linhas_mt_chave_candidata
    ON nivon_agro_staging.zarc_linhas_mt
        (source_sha256, chave_logica_sha);

-- Não há UNIQUE(municipio,cultura,ciclo,solo,manejo): combinação NÃO foi
-- comprovada única na base; não descartar duplicatas da fonte.
-- Não há GRANT adicional nem criação de usuário/role.
COMMIT;
