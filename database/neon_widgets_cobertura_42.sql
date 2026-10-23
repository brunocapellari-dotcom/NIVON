-- NIVON: cobertura dos 42 IDs catalogados (metadados; NÃO são endpoints de coleta).
-- Fontes com referência real: CEPEA/BCB. IMEA apenas staging por dia de PUBLICAÇÃO.
-- Views read-only; não há criação de cotação atual nem promoção de preços do IMEA.
CREATE OR REPLACE VIEW public.nivon_widgets_imea_publicacoes_v AS
SELECT CASE
        WHEN s.chain='soja' AND s.indicator_id='708192508838936580' THEN 199
        WHEN s.chain='milho' AND s.indicator_id='708192508838936581' THEN 198
       END::integer AS id_widget,
       'IMEA'::text AS fonte_original,
       s.chain::text AS produto,
       s.indicator_id::text AS indicador_fonte,
       s.indicator_name::text AS nome_indicador,
       s.location::text AS praca,
       s.unit::text AS unidade,
       s.price::numeric AS preco_informado,
       s.published_at::date AS dia_publicacao,
       s.reference_date::date AS data_referencia,
       s.first_collected_at AS primeira_coleta,
       s.last_seen_at AS ultima_observacao,
       s.source_url AS url_fonte,
       s.source_key AS chave_serie,
       s.version_hash AS hash_versao,
       s.quality_status AS status_qualidade,
       FALSE AS elegivel_tendencia_diaria,
       'PUBLICACAO_SEM_REFERENCIA'::text AS motivo_bloqueio
FROM public.nivon_imea_prices_staging s
WHERE s.source_name='IMEA'
  AND s.quality_status='PUBLISHED_DATE_ONLY'
  AND s.reference_date IS NULL
  AND s.indicator_kind='PRECO'
  AND s.unit='R$/sc'
  AND s.price > 0
  AND s.published_at IS NOT NULL
  AND s.source_url LIKE 'https://api1.imea.com.br/api/v2/mobile/cadeias/%/cotacoes'
  AND (
    (s.chain='soja' AND s.indicator_id='708192508838936580' AND s.indicator_name='Preço soja disponível compra')
    OR (s.chain='milho' AND s.indicator_id='708192508838936581' AND s.indicator_name='Preço milho disponível compra')
  );

CREATE OR REPLACE VIEW public.nivon_widgets_cobertura_v AS
WITH catalogo(id_widget,categoria,nome_widget,tipo,fonte_catalogada) AS (
  VALUES
    (131,'algodao','Algodão — IMEA','fisico','IMEA'),
    (84,'algodao','Algodão — Indicador CEPEA/ESALQ','fisico','CEPEA'),
    (168,'algodao','Algodão em pluma','fisico','A_CONFIRMAR'),
    (169,'algodao','Caroço de algodão','fisico','A_CONFIRMAR'),
    (55,'algodao','Algodão — Nova York','futuro','ICE US'),
    (222,'algodao','Índice Cotlook A','indice_fisico','Cotlook'),
    (302,'bovinos','Reposição Nelore — Macho','reposicao','A_CONFIRMAR'),
    (303,'bovinos','Reposição Nelore — Fêmea','reposicao','A_CONFIRMAR'),
    (299,'bovinos','Média de boi gordo — AgroBrazil','fisico','AgroBrazil'),
    (128,'bovinos','Indicador boi gordo ESALQ/B3','fisico','CEPEA'),
    (298,'bovinos','Indicador do boi','fisico','A_CONFIRMAR'),
    (300,'bovinos','Indicador da vaca','fisico','A_CONFIRMAR'),
    (301,'bovinos','Indicador da novilha','fisico','A_CONFIRMAR'),
    (248,'bovinos','Boi gordo — B3 pregão regular','futuro','B3'),
    (122,'bovinos','Boi à vista — IMEA','fisico','IMEA'),
    (200,'bovinos','Bezerro ESALQ/BM&F — MS','reposicao','CEPEA'),
    (28,'cafe','Café arábica — CEPEA/ESALQ','fisico','CEPEA'),
    (250,'cafe','Café arábica 4/5 — B3','futuro','B3'),
    (4,'cafe','Café — Nova York','futuro','ICE US'),
    (5,'cafe','Café — Londres','futuro','ICE Europe'),
    (104,'financeiro','Euro futuro','futuro','B3'),
    (17,'financeiro','Dólar comercial futuro','futuro','B3'),
    (232,'financeiro','Câmbio PTAX — dólar e euro','cambio','BCB'),
    (198,'milho','Milho disponível — IMEA','fisico','IMEA'),
    (130,'milho','Milho — mercado físico por praça','fisico','A_CONFIRMAR'),
    (10,'milho','Milho — Chicago','futuro','CME/CBOT'),
    (251,'milho','Milho — B3 pregão regular','futuro','B3'),
    (91,'milho','Indicador milho ESALQ/B3','fisico','CEPEA'),
    (199,'soja','Soja disponível — IMEA','fisico','IMEA'),
    (127,'soja','Soja — mercado físico por praça','fisico','A_CONFIRMAR'),
    (23,'soja','Soja — Chicago','futuro','CME/CBOT'),
    (22,'soja','Soja CME — B3 pregão regular','futuro','B3'),
    (82,'soja','Prêmio soja — Paranaguá','premio','A_CONFIRMAR'),
    (121,'soja','Indicador soja ESALQ/B3 — Paranaguá','fisico','CEPEA'),
    (26,'soja','Indicador soja CEPEA/ESALQ — Paraná','fisico','CEPEA'),
    (140,'soja','Óleo de soja — Chicago','futuro','CME/CBOT'),
    (139,'soja','Farelo de soja — Chicago','futuro','CME/CBOT'),
    (79,'soja','Farelo de soja — mercado físico','fisico','A_CONFIRMAR'),
    (36,'sucroenergetico','Açúcar cristal CEPEA/ESALQ — SP','fisico','CEPEA'),
    (223,'sucroenergetico','Etanol — Chicago','futuro','CME'),
    (249,'sucroenergetico','Etanol — B3 pregão regular','futuro','B3'),
    (35,'sucroenergetico','Açúcar — Nova York','futuro','ICE US')
),
fontes_verificadas AS (
 SELECT id_widget, count(*)::bigint AS observacoes_origem,
        MAX(data_referencia) AS ultima_data_referencia,
        MAX(data_coleta) AS ultima_coleta
 FROM public.nivon_widgets_origens_verificadas_v
 WHERE data_referencia IS NOT NULL
 GROUP BY id_widget
),
imea_apenas_publicacao AS (
 SELECT id_widget, count(*)::bigint AS publicacoes_em_staging,
        MAX(dia_publicacao) AS ultima_data_publicacao,
        MAX(ultima_observacao) AS ultima_coleta_staging
 FROM public.nivon_widgets_imea_publicacoes_v
 GROUP BY id_widget
)
SELECT c.id_widget,c.categoria,c.nome_widget,c.tipo,
       c.fonte_catalogada AS fonte_original_catalogada,
       COALESCE(v.observacoes_origem,0)::bigint AS observacoes_referenciadas,
       COALESCE(i.publicacoes_em_staging,0)::bigint AS publicacoes_imea_sem_referencia,
       v.ultima_data_referencia,i.ultima_data_publicacao,
       v.ultima_coleta,i.ultima_coleta_staging,
       CASE WHEN v.observacoes_origem > 0 THEN 'FONTE_PRIMARIA_COM_DATA_REFERENCIA'
            WHEN i.publicacoes_em_staging > 0 THEN 'IMEA_PUBLICACAO_SEM_DATA_REFERENCIA'
            ELSE 'CATALOGADO_SEM_DADO_PRIMARIO_VINCULADO'
       END::text AS estado_integracao,
       (v.observacoes_origem > 0)::boolean AS possivel_consulta_historica,
       FALSE::boolean AS widget_coletado_diretamente,
       FALSE::boolean AS google_cloud_carga_comprovada,
       CASE WHEN v.observacoes_origem > 0 THEN
          'Consultar origem CEPEA/BCB no Neon; widget serve somente como referencia editorial'
            WHEN i.publicacoes_em_staging > 0 THEN
          'Dados IMEA em staging; data de publicacao nao comprova data da cotacao; nao promover a tendencia'
            ELSE
          'Validar fonte primaria, permissao, serie e conector antes de publicar dados'
       END::text AS proximo_gate
FROM catalogo c
LEFT JOIN fontes_verificadas v USING(id_widget)
LEFT JOIN imea_apenas_publicacao i USING(id_widget);
