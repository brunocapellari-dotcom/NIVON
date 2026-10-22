-- Visões analíticas de fontes P0, read-only, sem interpolar informação histórica
-- como atual ou confundir variação observada com projeção.
CREATE OR REPLACE VIEW public.nivon_cepea_variacao_diaria_v AS
WITH latest_versions AS (
 SELECT DISTINCT ON(series_id,reference_date)
  series_id,product,location,unit,reference_date,price_brl,source_url,collected_at
 FROM public.nivon_cepea_prices WHERE quality_status='VALIDADO'
 ORDER BY series_id,reference_date,collected_at DESC,id DESC
), daily AS (
 SELECT *,LAG(price_brl) OVER (PARTITION BY series_id ORDER BY reference_date) AS previous_price,
  LAG(reference_date) OVER (PARTITION BY series_id ORDER BY reference_date) AS previous_date
 FROM latest_versions
)
SELECT series_id,product,location,unit,reference_date,price_brl,previous_price,previous_date,
 CASE WHEN previous_price IS NULL OR previous_price=0 THEN NULL
 ELSE ROUND((price_brl/previous_price-1)*100,4) END AS day_change_pct,
 CASE WHEN reference_date>=current_date-4 THEN 'REFERENCIA_RECENTE' ELSE 'SOURCE_LAG' END AS freshness,
 source_url,collected_at,'VARIACAO_DESCRITIVA_SEM_PREVISAO'::text AS metric_type
FROM daily;
CREATE OR REPLACE VIEW public.nivon_conab_producao_anual_v AS
WITH versions AS (
 SELECT DISTINCT ON(product,uf,crop_year)
  product,uf,crop_year,production_mil_t,area_planted_mil_ha,productivity_kg_ha,
  collected_at,source_uri,origin_kind
 FROM public.nivon_conab_series_historicas WHERE quality_status='VALIDADO'
 ORDER BY product,uf,crop_year,collected_at DESC,id DESC
)
SELECT product,uf,crop_year,production_mil_t,area_planted_mil_ha,productivity_kg_ha,
 LAG(production_mil_t) OVER (PARTITION BY product,uf ORDER BY crop_year) AS previous_production_mil_t,
 CASE WHEN LAG(production_mil_t) OVER(PARTITION BY product,uf ORDER BY crop_year) IS NULL
 OR LAG(production_mil_t) OVER(PARTITION BY product,uf ORDER BY crop_year)=0 THEN NULL
 ELSE ROUND((production_mil_t/LAG(production_mil_t) OVER(PARTITION BY product,uf ORDER BY crop_year)-1)*100,4)
 END AS yoy_production_change_pct,
 'HISTORICO_INFORMADO_NAO_COTACAO_ATUAL'::text AS metric_type,
 collected_at,source_uri,origin_kind
FROM versions;
