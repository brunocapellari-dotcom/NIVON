-- Interface para motores NIVON: apenas preço físico com referência comprovada
-- e coletor oficialmente saudável. Não retorna histórico como se fosse preço atual.
-- Uma falha CEPEA fecha a entrada automaticamente, sem apagar a série histórica.
CREATE OR REPLACE VIEW public.nivon_p0_precos_operacionais_v AS
SELECT q.series_id,q.product,q.location,q.unit,q.reference_date,q.price_brl,
 q.previous_price,q.day_change_pct,q.source_url,q.collected_at,
 s.operational_status,
 'PRECO_FISICO_CEPEA_COM_REFERENCIA_CONFIRMADA'::text AS use_class
FROM public.nivon_cepea_variacao_diaria_v q
JOIN public.nivon_p0_series_status_v s
 ON s.source='CEPEA' AND s.series_id=q.series_id
WHERE s.operational_status='CURRENT_AND_ACTIVE'
 AND q.freshness='REFERENCIA_RECENTE'
 AND q.reference_date=s.last_reference_date
 AND q.reference_date<=current_date
 AND q.reference_date>=current_date-4;
-- IMEA sem reference_date não participa desta interface.
-- CONAB contém dados agrícolas históricos, não preços físicos.
