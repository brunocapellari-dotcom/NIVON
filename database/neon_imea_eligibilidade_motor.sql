-- IMEA: camada de acesso para motores.
-- A fonte informa data_publicacao; ausência de data_referencia bloqueia tendência diária.
-- Revisões são preservadas em staging por (source_key, version_hash).
CREATE OR REPLACE VIEW public.nivon_imea_indicadores_verificados_v AS
WITH latest AS (
 SELECT DISTINCT ON(chain,indicator_id,location,unit,crop_year,published_at)
   chain,indicator_id,indicator_name,location,unit,crop_year,price,published_at,
   reference_date,source_url,source_key,version_hash,quality_status,
   first_collected_at,last_seen_at
 FROM public.nivon_imea_prices_staging
 WHERE source_name='IMEA' AND price>0
 ORDER BY chain,indicator_id,location,unit,crop_year,published_at,
          last_seen_at DESC,id DESC
)
SELECT chain,indicator_id,indicator_name,location,unit,crop_year,price,
 published_at,reference_date,source_url,source_key,version_hash,quality_status,
 first_collected_at,last_seen_at,
 CASE WHEN reference_date IS NULL THEN 'PUBLICACAO_SEM_REFERENCIA'
      WHEN quality_status<>'VALIDADO' THEN 'NAO_HOMOLOGADO'
      WHEN reference_date<current_date-5 THEN 'SOURCE_LAG'
      ELSE 'ELEGIVEL_COM_REFERENCIA' END AS analysis_eligibility
FROM latest;
