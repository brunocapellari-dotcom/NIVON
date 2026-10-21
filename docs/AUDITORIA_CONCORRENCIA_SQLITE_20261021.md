# NIVON — Auditoria R03 de concorrência SQLite
**Data:** 2026-10-21 | **componente:** `src/nivon/registro_snapshots.py` + `src/nivon/transacoes_sqlite.py`.  
**Escopo:** fluxo offline de registro de 48 vintages sintéticas em um arquivo SQLite temporário com 16 processos independentes, três escritas por processo. Sem dados reais, rede, deploy ou custos.  
**Base:** integração PR #13, commit `9f1a5e0ded09ac2246cc83b764ddb60f44436986`.  
**PR de auditoria:** #35, branch `audit/sqlite-concorrencia-20261021`.  
**Classificação:** **REPROVADO — NC-AUD-015 (P0) para ingestão concorrente**.

## Evidências reais de CI

| Execução | SHA de testes | Resultado |
|---|---|---|
| https://github.com/brunocapellari-dotcom/NIVON/actions/runs/39591857481 | `cc2c5990d78b3574a0fd1960342105ef3de0a9cb` | 16 processos, 10 retornaram `OperationalError: database is locked`; suíte: 885 testes, 1 falha, 5 skipped |
| https://github.com/brunocapellari-dotcom/NIVON/actions/runs/39591992517 | `d3e7b90492e7a86d98a642f65d733215a326b78c` | 16 processos, 8 retornaram `database is locked`; 24/48 snapshots e 24/48 coletas persistidos; suíte: 885 testes, 1 falha, 5 skipped |

No **segundo reteste**, o teste inspecionou o banco mesmo após detectar erros. `PRAGMA integrity_check` retornou `ok`, e `foreign_key_check` não acusou vínculos inválidos: evidência de **arquivo consistente**, mas ingestão **incompleta**. Não confundir ausência de corrupção com sucesso transacional E2E. Nenhuma escrita sintética faltante foi automaticamente reexecutada até completar 48.

## Mecanismo suspeito e restrições

- O processo usa conexão SQLite independente (`timeout=5` no teste), barreira de largada e três `registrar_snapshot` por processo.
- `registrar_snapshot` faz `SELECT` antes de `INSERT` dentro de `savepoint_atomico`, que usa `SAVEPOINT` sem adquirir lock de escritor de modo antecipado. Transações concorrentes iniciadas de forma adiada podem disputar conversão de lock de leitura para escrita e receber `SQLITE_BUSY`.
- Esta é uma **hipótese técnica sustentada pelo código e comportamento**, não prova isolada de todos os fatores responsáveis pelo lock.
- A timeout configurada isoladamente não resolve necessariamente upgrade de lock concorrente; backoff/retry deve repetir a **transação inteira**, incluindo o `SELECT`, com limites, e jamais esconder erro ou deixar dados parcialmente gravados.
- Manter savepoints aninhados quando houver transação externa preexistente; não executar `BEGIN IMMEDIATE` dentro de transação ativa. Projetar um gerenciador transacional canônico na borda para `BEGIN IMMEDIATE` e, se adequado, WAL e `busy_timeout`, com concorrência e rollback testados.

## Correção obrigatória e reteste

1. Criar contrato único de escrita concorrente com política de lock/retry limitada, idempotência por `dataset_id+sha256` e preservação de vintages.
2. Demonstrar que 16 processos completam 48 escritas, com zero exceções, sem reprocessamentos silenciosos, exatamente 48 snapshots e coletas e `integrity_check=ok`.
3. Acrescentar segunda bateria: 16 processos com SHA igual e horários de coleta distintos, confirmando somente um snapshot e todas as coletas.
4. Confirmar rollback de transação externa e recuperação após indisponibilidade; observar métricas de `SQLITE_BUSY`, latência, retries, falhas definitivas, filas e idempotência.
5. Testar backup e restore com o banco efetivamente concorrido e WAL, caso adotado. Backup local não prova recuperação remota, criptografia ou SLA produtivo.
6. Reexecutar os testes no SHA de integração final antes de aprovar operação. Até lá, estado **não homologado**.

Este relatório é registro de auditoria independente, não PR de correção da implementação.
