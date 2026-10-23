-- NIVON: painel SQL factual do ZARC, sem insinuar dados importados onde não há.
CREATE OR REPLACE VIEW nivon_agro_staging.v_zarc_estado_operacional AS
WITH
 ultima_validacao AS (
   SELECT v.* FROM nivon_agro_staging.zarc_validacoes_arquivo v
   ORDER BY collected_utc DESC, run_github DESC LIMIT 1
 ),
 ultimo_ckan AS (
   SELECT s.* FROM nivon_agro_staging.zarc_ckan_sinais s
   ORDER BY coletado_em DESC LIMIT 1
 ),
 anterior_ckan AS (
   SELECT s.* FROM nivon_agro_staging.zarc_ckan_sinais s
   ORDER BY coletado_em DESC OFFSET 1 LIMIT 1
 ),
 totais AS (
   SELECT
     (SELECT COUNT(*) FROM nivon_agro_staging.zarc_edicoes) AS edicoes_postgres,
     (SELECT COUNT(*) FROM nivon_agro_staging.zarc_linhas_mt) AS linhas_mt_postgres,
     (SELECT COUNT(*) FROM nivon_agro_staging.zarc_ckan_sinais) AS observacoes_ckan
 )
SELECT
 'ZARC_JANELAS'::text AS dataset_id,
 (SELECT collected_utc FROM ultima_validacao) AS ultima_validacao_real_em,
 (SELECT source_sha256 FROM ultima_validacao) AS sha_csv_ultima_validacao,
 (SELECT mt_rows FROM ultima_validacao) AS mt_linhas_validadas_quarentena,
 (SELECT brazil_rows FROM ultima_validacao) AS brasil_linhas_validadas_quarentena,
 (SELECT run_github FROM ultima_validacao) AS prova_github,
 (SELECT coletado_em FROM ultimo_ckan) AS ultimo_sinal_ckan_em,
 (SELECT recurso_revision_id FROM ultimo_ckan) AS revisao_ckan_atual,
 (SELECT recurso_revision_id FROM anterior_ckan) AS revisao_ckan_anterior,
 CASE WHEN (SELECT recurso_revision_id FROM anterior_ckan) IS NULL THEN NULL
      ELSE (SELECT recurso_revision_id FROM ultimo_ckan)
          IS DISTINCT FROM (SELECT recurso_revision_id FROM anterior_ckan)
 END AS revisao_ckan_mudou,
 t.observacoes_ckan,t.edicoes_postgres,t.linhas_mt_postgres,
 (SELECT archived_to_private_bucket FROM ultima_validacao) AS arquivo_raw_arquivado,
 (SELECT rows_loaded_to_agro_database FROM ultima_validacao) AS dados_reais_inseridos,
 (SELECT approved_for_publication FROM ultima_validacao) AS liberado_publicacao,
 CASE
   WHEN t.linhas_mt_postgres>0
      THEN 'LINHAS_POSTGRES_EXISTENTES_CONFERIR_INTEGRIDADE'
   WHEN (SELECT source_sha256 FROM ultima_validacao) IS NOT NULL
      THEN 'VALIDACAO_REAL_CONCLUIDA_SEM_CARGA_DURAVEL'
   ELSE 'SEM_VALIDACAO_REAL_REGISTRADA'
 END AS etapa_operacional
FROM totais t;
