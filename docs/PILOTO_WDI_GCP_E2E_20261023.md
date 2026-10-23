# NIVON — Piloto controlado de persistência Google Cloud

Teste de aceitação operacional preparado em 23/10/2026. **Ainda não executado na nuvem.**

## Critério GO / NO-GO
Piloto exclusivo de UMA observação histórica do Banco Mundial: Brasil, rendimento de cereais `AG.YLD.CREL.KG`, ano 2024 (kg/ha).
Fluxo obrigatório:
1. WIF/ADC e preflight de tabela `nivon_observacoes` já existente no dataset aprovado.
2. Coleta via API pública real, conferindo fonte/país/indicador/ano/unidade e exatamente uma observação.
3. Stage SQLite local + RAW SHA-256.
4. RAW imutável no GCS. Falha impede MERGE.
5. Stage JSONL e manifesto recuperável no GCS. Falha impede MERGE.
6. BigQuery MERGE com podas de partição, dry-run e limite de bytes.
7. Readback de snapshot GCS (SHA) e da observação BigQuery, confirmando fingerprint.

Somente quando todos os passos passarem, retornar `PILOTO_WDI_CONFIRMACAO_E2E`. Esse status não comprova que todas as demais fontes ou a coleta recorrente funcionam.

## Gate e execução pela interface
Workflow: [NIVON - Piloto real WDI GCS BigQuery](https://github.com/brunocapellari-dotcom/NIVON/actions/workflows/piloto-wdi-gcp-e2e.yml).

- Executar apenas na branch `main` por `workflow_dispatch`, sob GitHub Environment `nivon-gcp-producao`.
- Antes de executar, confirmar existência de `nivon-data.nivon_raw.nivon_observacoes` (via bootstrap unificado), orçamento/alertas, IAM WIF mínimo para **criar objetos e jobs** no dataset e bucket.
- Exige `NIVON_PILOTO_WDI_GCP_APPROVED=true`, `NIVON_ZERO_COST_BQ_APPROVED=true`, `NIVON_RAW_ARCHIVE_APPROVED=true`, `NIVON_RECOVERABLE_STAGE_APPROVED=true`, além das variáveis WIF/projeto/dataset/bucket.
- Requer validação de atribuição e permissão de uso do indicador do Banco Mundial. Não redistribui dados publicamente.
- A presença dos gates não garante gasto R$0. Nunca armazenar chave JSON no GitHub.
- Fluxo sem cron e sem criação automática de tabelas.

## Saídas
Recibo impresso no GitHub Actions com hash do snapshot RAW, SHA-256 do manifesto (para replay), confirmação GCS e BigQuery. Em erro, job falha, não declara sucesso. Não excluir o objeto parcial para preservar auditoria e repetição idempotente.

**Status:** código integrado no branch de desenvolvimento; testes simulados não substituem uma execução autenticada real no Cloud.
