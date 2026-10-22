# NIVON — Monitoramento de cobertura PTAX por janela

**Evidência:** auditoria SQL **somente leitura** executada no Neon operacional em 22/10/2026 00:50:44 UTC, quando o dia local na região `America/Sao_Paulo` era 21/10/2026. A consulta está em `database/neon_ptax_backfill_health.sql`.

## Estado verificado (fotografia, sujeito a evolução do agendador)

| Métrica | USD | EUR |
|---|---:|---:|
| Janelas históricas planejadas | 81 | 81 |
| Janelas concluídas por checkpoint | 8 | 8 |
| Janelas pendentes | 73 | 73 |
| Progresso de janelas | 9,9% | 9,9% |
| Continuidade dos checkpoints históricos até | 04/09/2020 | 04/09/2020 |
| Próxima janela pendente | 05/09/2020–05/10/2020 | 05/09/2020–05/10/2020 |
| Cotações armazenadas (diárias + backfill) | 178 | 888 |
| Datas de referência distintas armazenadas | 178 | 178 |
| Erros registrados de backfill / diário | 0 / 0 | 0 / 0 |
| Checkpoints não pertencentes à grade histórica (diário recente) | 1 | 1 |

**Importante:** as 81 janelas, iniciadas em 01/01/2020, são períodos de 31 dias definidos pelo código do coletor, incluindo uma janela final parcial, calculados até o dia local da auditoria. A conclusão de uma janela é dada por checkpoint `SUCCESS` ou `EMPTY`, e **não garante a existência de preços em todos os dias de negociação**. Um checkpoint diário na faixa 2026 não conta como backfill do intervalo 2020–2026.

As cotações e o estágio do backfill mudam enquanto o trigger horário está ativo. Não extrapolar a taxa de 8 janelas para prometer data exata de conclusão, nem aumentar frequência sem medir limites de Neon/BCB.

## Como repetir (sem alterar banco)

Execute `database/neon_ptax_backfill_health.sql` no banco de origem Neon `nivon`, com permissão somente leitura. O SQL devolve uma coluna JSON `backfill_health` e não lê campos de preço nem autenticação. Salve apenas esse objeto agregado em arquivo local e execute:

```sh
python3 scripts/validate_ptax_backfill_health.py --input /caminho/privado/ptax-health.json
```

O JSON de saída contém estatísticas, janela seguinte, avisos e gates de migração. Nenhuma consulta remota é executada pelo validador. Código de saída zero significa somente que o manifesto é coerente, não que há backup, cobertura completa ou autorização BigQuery.

## Regras de alerta e integração editorial

- `HISTORICAL_WINDOWS_PENDING`: existem janelas de histórico não processadas.
- `OUT_OF_ORDER_COMPLETED_WINDOWS`: há checkpoint mais recente depois de um buraco anterior; não usar o maior checkpoint como watermark contínuo.
- `COLLECTOR_REPORTED_ERRORS`: o banco registrou erros de execução.
- `BACKFILL_LAST_RUN_OLDER_THAN_3H`: a última execução bem-sucedida é antiga em relação ao instante do relatório; regra diagnóstica que exige checagem da agenda e da disponibilidade, não um incidente automaticamente confirmado.
- `NO_SUCCESSFUL_DAILY_RUN` e `NO_SUCCESSFUL_BACKFILL`: faltam execuções suficientes para inferir atividade.

A atualização diária de PTAX tem `data_referencia` distinta da data de coleta e não pode ser rotulada como preço “de hoje” apenas por um checkpoint novo. Para validar freshness real, é obrigatório considerar o calendário de dias úteis/feriados de publicação do BCB e as características específicas de USD e EUR.

Mesmo quando `pending_windows=0`, o status correto é `CHECKPOINTS_COMPLETE_SOURCE_NOT_AUDITED` até reconciliação independente com a API primária, preços, revisão, cobertura de pregões e um backup restaurável. Sempre `history_complete=false` e `cutover_allowed=false` nesta fase.

## Bloqueios persistentes

- A auditoria de faturamento/IAM de `nivon-data` ainda não foi recebida por interface autenticada acessível a esta conversa. Não criar recursos de nuvem.
- Inventário Neon observou zero snapshots cadastrados e agenda de snapshots vazia; isso não descarta retenção interna do provedor e não substitui backup externo privado e restauração testada.
- Não alterar trigger diário, histórico, banco operacional ou assinaturas de serviços sem necessidade comprovada.
- PR #58 mantém o coletor Neon; PR #84 é plano/instrumentação, ainda draft. O estado de `main` não foi alterado.

**Critérios para próxima rodada:** reproduzir auditoria após uma execução real adicional, comparar watermark e intervalos, distinguir progresso/estabilidade/erro, conferir as cotas do plano Free, e testar backup de dados reais apenas por via segura autorizada.
