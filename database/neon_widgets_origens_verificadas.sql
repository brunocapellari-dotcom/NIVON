-- NIVON — ponte auditável entre widgets catalogados e séries primárias existentes.
-- Dados vêm do CEPEA e Banco Central armazenados no Neon, NÃO de scraping de widgets.
-- View de leitura: não transfere nem cria dados no Google Cloud.
-- Não altera nem dá acesso à Inteligência Pecuária nos relatórios agrícolas; filtros editoriais seguem separados.
-- A ausência de data_publicacao na fonte continua NULL.
CREATE OR REPLACE VIEW public.nivon_widgets_origens_verificadas_v AS
WITH cepea AS (
    SELECT
        CASE p.series_id
            WHEN 'soja_paranagua' THEN 121
            WHEN 'soja_parana' THEN 26
            WHEN 'milho_esalq_b3' THEN 91
        END::integer AS id_widget,
        'CEPEA'::text AS fonte_original,
        p.series_id::text AS serie_origem,
        p.product::text AS produto,
        p.location::text AS praca,
        NULL::text AS detalhe_cotacao,
        p.unit::text AS unidade,
        p.price_brl::numeric AS valor,
        p.reference_date::date AS data_referencia,
        p.published_at::timestamptz AS data_publicacao,
        p.collected_at::timestamptz AS data_coleta,
        p.epistemic_type::text AS natureza,
        p.quality_status::text AS status_qualidade,
        p.license::text AS licenca,
        p.source_url::text AS url_fonte_original,
        p.source_key::text AS chave_origem,
        p.version_hash::text AS hash_versao
    FROM public.nivon_cepea_prices AS p
    WHERE p.series_id IN ('soja_paranagua','soja_parana','milho_esalq_b3')
      AND p.quality_status = 'VALIDADO'
      AND p.epistemic_type = 'INFORMADO'
),
ptax AS (
    SELECT
        232::integer AS id_widget,
        'BCB'::text AS fonte_original,
        ('ptax_' || q.currency || '_' || lower(s.lado))::text AS serie_origem,
        q.currency::text AS produto,
        NULL::text AS praca,
        (q.bulletin_type || ' / ' || q.quote_time_original || ' / ' || s.lado)::text AS detalhe_cotacao,
        q.unit::text AS unidade,
        s.valor::numeric AS valor,
        q.reference_date::date AS data_referencia,
        q.published_at::timestamptz AS data_publicacao,
        q.first_collected_at::timestamptz AS data_coleta,
        q.observation_kind::text AS natureza,
        'REGISTRO_NEON'::text AS status_qualidade,
        q.license::text AS licenca,
        NULL::text AS url_fonte_original,
        ('neon_ptax_quotes:' || q.id || ':' || lower(s.lado))::text AS chave_origem,
        NULL::text AS hash_versao
    FROM public.nivon_ptax_quotes AS q
    CROSS JOIN LATERAL (VALUES ('COMPRA',q.buy_brl),('VENDA',q.sell_brl)) AS s(lado, valor)
    WHERE q.currency IN ('USD','EUR')
      AND q.observation_kind = 'INFORMADO'
      AND s.valor IS NOT NULL
)
SELECT *, FALSE::boolean AS widget_coletado_diretamente FROM cepea
UNION ALL
SELECT *, FALSE::boolean AS widget_coletado_diretamente FROM ptax;
