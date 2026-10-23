-- NIVON: qualidade operacional dos 42 widgets; critério de 5 dias é ALERTA,
-- não equivale a calendário de pregão nem a certificação de cotação atual.
-- Usa as views vivas do Neon (não há sincronização declarada no Google Cloud).
CREATE OR REPLACE VIEW public.nivon_widgets_saude_v AS
SELECT
 c.id_widget,
 c.categoria,
 c.nome_widget,
 c.fonte_original_catalogada,
 c.estado_integracao,
 c.observacoes_referenciadas,
 c.publicacoes_imea_sem_referencia,
 c.ultima_data_referencia,
 c.ultima_data_publicacao,
 c.ultima_coleta,
 c.ultima_coleta_staging,
 CASE WHEN c.ultima_data_referencia IS NOT NULL
      THEN (CURRENT_DATE - c.ultima_data_referencia)::integer
      ELSE NULL::integer END AS dias_corridos_desde_referencia,
 CASE WHEN c.ultima_data_publicacao IS NOT NULL
      THEN (CURRENT_DATE - c.ultima_data_publicacao)::integer
      ELSE NULL::integer END AS dias_corridos_desde_publicacao,
 CASE
   WHEN c.estado_integracao='IMEA_PUBLICACAO_SEM_DATA_REFERENCIA'
     THEN 'BLOQUEADO_PARA_TENDENCIA_SEM_REFERENCIA'
   WHEN c.observacoes_referenciadas = 0
     THEN 'SEM_SERIE_PRIMARIA_CONSULTAVEL'
   WHEN c.ultima_data_referencia IS NULL
     THEN 'DATA_REFERENCIA_AUSENTE'
   WHEN c.ultima_data_referencia > CURRENT_DATE
     THEN 'ERRO_DATA_FUTURA'
   WHEN c.ultima_data_referencia < CURRENT_DATE - 5
     THEN 'ALERTA_REFERENCIA_COM_MAIS_DE_5_DIAS_CORRIDOS'
   ELSE 'REFERENCIA_DENTRO_DE_5_DIAS_CORRIDOS_NAO_HOMOLOGA_TEMPO_REAL'
 END::text AS estado_saude,
 FALSE::boolean AS qualidade_intraday_comprovada,
 FALSE::boolean AS carga_google_cloud_verificada
FROM public.nivon_widgets_cobertura_v c;
