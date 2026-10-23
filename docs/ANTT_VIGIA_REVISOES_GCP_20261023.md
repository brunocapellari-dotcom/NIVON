# NIVON — vigia de revisões ANTT/SIADE ferroviário

**Implementação:** `src/nivon/antt_vigia_revisoes.py`, CI `.github/workflows/antt-vigia-revisoes-gcp.yml`.  
**Origem:** CKAN/CSV oficial ANTT/SIADE; destino somente leitura `nivon-data.nivon_raw.vw_antt_ferrovia_od_atual`.

## Situação que motivou o monitor

O histórico de 2006–agosto de 2026 já foi carregado e comprovado no Google Cloud. A auditoria independente concluiu 21 anos, **174.850 OD e 9.952.668.869 TU acumuladas** em https://github.com/brunocapellari-dotcom/NIVON/actions/runs/40001461762. Os dados ferroviários não devem ser somados a volumes rodoviários ou hidroviários como se fossem cargas distintas, pois há transbordos.

Em https://github.com/brunocapellari-dotcom/NIVON/actions/runs/39999355921 o histórico 2006–2021 foi gravado em cinco lotes; 2022–2025 foram conciliados em https://github.com/brunocapellari-dotcom/NIVON/actions/runs/39998589364; 2026 parcial em https://github.com/brunocapellari-dotcom/NIVON/actions/runs/39983416188.

## Operação do vigia

- Uma vez por semana, segunda-feira 13h30 UTC, e em disparos manuais, baixar apenas os CSVs oficiais do ano corrente e anterior; em outubro de 2026, 2025 e 2026. A contingência usa URLs oficiais historicamente verificadas caso o catálogo CKAN retorne erro transitório, nunca bypass de HTTP 401/403.
- Os arquivos brutos ficam apenas no runner temporário. Comparar **SHA-256, número de registros, soma TU e competência máxima** com a versão atualmente selecionada na view BigQuery, sem alterar versões ou dados.
- Consulta BQ parametrizada por anos e limitada a 50 MB faturáveis por query (`maximum_bytes_billed`). Isso **não demonstra custo zero**, nem equivale a limite de fatura para toda a conta.
- Se uma revisão nova ou incompatibilidade for detectada, a execução termina em falha e registra estado `REVISAR_FONTE_ANTES_DE_PUBLICAR`; não faz upload, load, CREATE VIEW nem aprovação automática.
- O CSV informado como anual pode ser revisto retroativamente. O vigia semanal de 2 anos **não detecta revisões em 2006–2024**. Mantê-las sob inspeção histórica periódica separada, com custo e janela definidos antes de implementar.
- O vigia não interpreta TU como carga única multimodal, não homologa TKU sem validação de unidade e não substitui verificações portuárias/ANTAQ.

## Gate para incremento em produção

Após revisão oficial confirmada e QA de metodologia, produzir plano diferencial por ano; comparar contagens/hash, custos e permissões, exigir gate exclusivo ANTT e só então executar uma carga idempotente versionada. Revalidar a view após carregar. Essa etapa de **escrita incremental não é ativada por este vigia**.
