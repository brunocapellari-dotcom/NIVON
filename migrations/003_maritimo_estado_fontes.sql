-- NIVON 003: quadro de saúde/frescor (aditivo, sem dados sintéticos)
CREATE OR REPLACE VIEW nivon_maritimo.estado_fontes_v AS
 SELECT DISTINCT ON(fonte)
   fonte,
   coletado_em AS ultima_coleta,
   estado AS ultimo_estado,
   quantidade AS registros_ultima_coleta,
   revisoes AS revisoes_ultima_coleta,
   motivo AS motivo_ultimo_estado,
   duracao_ms,
   CASE WHEN coletado_em < NOW() - INTERVAL '12 hours'
        THEN 'ATRASADA' ELSE 'RECENTE' END AS frescor
 FROM nivon_maritimo.coleta_execucoes
 ORDER BY fonte, coletado_em DESC, run_id DESC;
