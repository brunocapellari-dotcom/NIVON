# Inventário de branches sem PR aberta — 26/10/2026

**NÃO APAGAR SEM APROVADO.** O inventário abaixo parte da coleção real de branches e das PRs abertas. O sufixo de data no nome é apenas *indício*, não prova da última atividade. A confirmação de **mesclada** exige análise de ancestralidade; a de **abandonada há mais de três dias** exige a data real do último commit. Não classificar nome como prova.

- Branches totais no momento da consulta: **319**.
- PRs abertas consultadas: **133**.
- Branches sem PR aberta (exceto `main`): **185**.
- Com nome indicando data anterior a 23/10: **39** (somente candidatas a abandono).
- Com nome indicando 23/10 ou posterior: **135**.
- Sem data interpretável no nome: **11**.

**Apuração técnica de 26/10/2026.** Mesclada = zero commits à frente da main; corte de inatividade: 23/10/2026 17:09 UTC. Atenção: squash/cherry-pick pode incorporar conteúdo sem ancestralidade; não excluir até revisão. A branch F1 saiu da relação pois tem PR #337 aberta.

## Resultado da conferência

| Situação | Quantidade |
|---|---:|
| Branches órfãs no snapshot, sem F1 | 184 |
| Mescladas por ancestralidade | 16 |
| Não mescladas por ancestralidade | 168 |
| Último commit há mais de três dias | 70 |
| Não mescladas e antigas | 66 |
| Com commit recente | 114 |
| Data não confirmada | 0 |

## Já mescladas por ancestralidade
- `feat/bootstrap-acessos-protegidos-main-20261021`
- `feat/go-live-portal-interno-20261025`
- `feat/hidromet-fontes-publicas-power-glofas-20261021`
- `feat/meteo-publica-inmet-cptec-20261021`
- `feat/nivon-ais-geocercas-evidencia-inferida-20261025`
- `feat/nivon-ais-ledger-replay-e2e-20261025`
- `feat/nivon-go-live-painel-interno-gcs-20261025`
- `feat/nivon-go-live-rotina-dias-uteis-20261025`
- `feat/nivon-maritime-readonly-bigquery-panel-20261023`
- `feat/nivon-painel-integrado-logistica-maritimo-quant-20261023`
- `feat/portal-gcs-cloudrun-privado-20261025`
- `fix/antaq-hf-revision-file-size-pinned-20261025`
- `fix/go-live-controlar-gcp-execucoes-20261025`
- `fix/golive-readonly-staging-opcional-20261025`
- `fix/nivon-go-live-gcs-append-only-20261025`
- `fix/workflow-inmet-runner-context-20261021`

## Não mescladas e sem commit há mais de três dias — NÃO EXCLUIR
- `docs/antt-gcp-operacao-atualizada-20261023`
- `docs/catalogo-faostat-qcl-validado-20261021`
- `docs/evidencia-antt-gcp-operacional-20261023`
- `docs/evidencias-smoke-fontes-20261021`
- `docs/homologacao-eurostat-faostat-20261021`
- `docs/homologacao-flood-ensemble-fpma-20261021`
- `feat/antaq-hidrovia-produtos-20261023`
- `feat/antaq-historico-qualidade-lineup-20261019`
- `feat/antaq-monitor-disponibilidade-20261023`
- `feat/antt-2026-primeira-carga-unica-gcp-20261023`
- `feat/antt-anuario-rgi-20261023`
- `feat/antt-mdfe-volumes-od-20261022`
- `feat/antt-piloto-gcp-preparacao-20261023`
- `feat/apis-flood-ensemble-fao-fpma-20261021`
- `feat/bcb-focus-expectativas-20261021`
- `feat/brasilapi-refs-nivon-20261021`
- `feat/catalogo-fontes-gratuitas-20261021`
- `feat/coleta-gcp-nucleo-main-20261023`
- `feat/coleta-real-camadas-20261022`
- `feat/coletores-apis-gratuitas-reais-20261021`
- `feat/conectores-gcp-conab-sgs-20261023`
- `feat/conectores-google-cloud-lote1-20261023`
- `feat/connectores-gtr-noaa-pinksheet-geodata-20261021`
- `feat/connectores-publicos-inpe-cftc-antt-20261021`
- `feat/consulta-analitica-bq-fontes-20261023`
- `feat/corredores-ferroviarios-estacoes-20261023`
- `feat/corredores-primeira-view-bq-real-20261023`
- `feat/earthsearch-usda-gtr-bases-20261021`
- `feat/eurostat-faostat-qcl-api-20261021`
- `feat/expansao-50-fontes-20261022`
- `feat/faostat-bulk-manifest-20261021`
- `feat/faostat-qcl-bigquery-contract-20261021`
- `feat/faostat-qcl-stream-sqlite-20261021`
- `feat/fontes-complementares-glam-wapor-portwatch-20261021`
- `feat/fontes-ibge-worldbank-operacionais-20261023`
- `feat/gcp-wif-smoke-leitura-20261023`
- `feat/integracoes-lineup-nacional-20261019`
- `feat/inteligencia-corredores-intermodais-20261023`
- `feat/ivo-cerebro-historico-20261019`
- `feat/lineup-itaqui-codeba-20261019`
- `feat/migracao-neon-para-gcp-20261023`
- `feat/ptax-bcb-agendamento-wif-escritor-unico-20261023`
- `feat/series-corredores-antt-bigquery-20261023`
- `feat/sisfogo-roi-fonte-oficial-20261021`
- `feat/soilgrids-embrapa-solos-20261021`
- `feat/verificacao-cloud-gcp-20261023`
- `feature/transporte-antt-antaq-20261022`
- `fix/antt-bq-readiness-20261023`
- `fix/antt-ckan-fallback-verificado-20261023`
- `fix/antt-ckan-retry-20261023`
- `fix/antt-fallback-csv-oficial-20261023`
- `fix/antt-gcp-precise-gates-20261023`
- `fix/antt-gcp-unificar-config-20261023`
- `fix/antt-rgi-smoke-main-20261023`
- `fix/formatos-reais-noaa-gtr-wb-esa-20261021`
- `fix/gcp-regiao-inventario-destinos-20261023`
- `fix/nivon-gcp-migracao-controle-operacional-20261023`
- `fix/noaa-mei-missing-sentinel-20261021`
- `fix/open-meteo-ensemble-control-20261021`
- `fix/p0-antt-rgi-ci-separado-20261023`
- `integration/base-gcp-coletor-20261023`
- `review/nivon-ciencia-base-20261019`
- `test/qa-faostat-qcl-zip-once-20261021`
- `test/smoke-eurostat-faostat-qcl-20261021`
- `test/smoke-flood-ensemble-fpma-20261021`
- `test/smoke-fontes-publicas-20261021`

## Branches sem PR aberta

| Branch | Sinal do nome | Mesclada na main? | Último commit > 3 dias? |
|---|---|---|---|
| `ci/antaq-2025-repetir-hf-realpath-20261025` | 20261025 | NÃO MESCLADA — 1 commit(s) à frente |2026-10-26T01:18:21Z — RECENTE |
| `ci/antt-rgi-reexecucao-corrigida-20261023` | 20261023 | NÃO MESCLADA — 1 commit(s) à frente |2026-10-23T19:11:33Z — RECENTE |
| `claude/auto-cepea-disponibilidade` | sem data | NÃO MESCLADA — 1 commit(s) à frente |2026-10-26T03:36:48Z — RECENTE |
| `claude/auto-monitor-frescor` | sem data | NÃO MESCLADA — 2 commit(s) à frente |2026-10-26T03:37:29Z — RECENTE |
| `claude/auto-testes-agrobr-setoriais` | sem data | NÃO MESCLADA — 1 commit(s) à frente |2026-10-26T15:35:40Z — RECENTE |
| `codex/go-live-checkpoint` | sem data | NÃO MESCLADA — 11 commit(s) à frente |2026-10-26T02:53:41Z — RECENTE |
| `codex/286-remove-vercel` | sem data | NÃO MESCLADA — 2 commit(s) à frente |2026-10-26T02:31:06Z — RECENTE |
| `codex/287-single-private-interface` | sem data | NÃO MESCLADA — 2 commit(s) à frente |2026-10-26T02:41:44Z — RECENTE |
| `codex/288-gcp-readiness` | sem data | NÃO MESCLADA — 1 commit(s) à frente |2026-10-26T02:34:17Z — RECENTE |
| `codex/289-antt-reader-contract` | sem data | NÃO MESCLADA — 1 commit(s) à frente |2026-10-26T02:38:04Z — RECENTE |
| `codex/290-operation-smoke` | sem data | NÃO MESCLADA — 3 commit(s) à frente |2026-10-26T02:47:09Z — RECENTE |
| `codex/291-source-health` | sem data | NÃO MESCLADA — 1 commit(s) à frente |2026-10-26T02:50:48Z — RECENTE |
| `docs/antt-21anos-corredores-operacional-20261023` | 20261023 | NÃO MESCLADA — 2 commit(s) à frente |2026-10-23T18:18:40Z — RECENTE |
| `docs/antt-gcp-operacao-atualizada-20261023` | 20261023 | NÃO MESCLADA — 1 commit(s) à frente |2026-10-23T12:16:03Z — MAIS DE 3 DIAS |
| `docs/antt-rodovia-rgi-2025-provas-custo-20261023` | 20261023 | NÃO MESCLADA — 2 commit(s) à frente |2026-10-23T19:25:16Z — RECENTE |
| `docs/catalogo-faostat-qcl-validado-20261021` | 20261021 | NÃO MESCLADA — 461 commit(s) à frente |2026-10-22T00:18:57Z — MAIS DE 3 DIAS |
| `docs/evidencia-antt-gcp-operacional-20261023` | 20261023 | NÃO MESCLADA — 2 commit(s) à frente |2026-10-23T16:09:58Z — MAIS DE 3 DIAS |
| `docs/evidencias-smoke-fontes-20261021` | 20261021 | NÃO MESCLADA — 450 commit(s) à frente |2026-10-21T21:00:22Z — MAIS DE 3 DIAS |
| `docs/homologacao-eurostat-faostat-20261021` | 20261021 | NÃO MESCLADA — 456 commit(s) à frente |2026-10-21T23:09:36Z — MAIS DE 3 DIAS |
| `docs/homologacao-flood-ensemble-fpma-20261021` | 20261021 | NÃO MESCLADA — 453 commit(s) à frente |2026-10-21T21:24:42Z — MAIS DE 3 DIAS |
| `docs/nivon-github-fontes-complementares-20261026` | 20261026 | NÃO MESCLADA — 3 commit(s) à frente |2026-10-26T15:34:23Z — RECENTE |
| `docs/trimodal-real-2025-consolidar-e-desarmar-push-20261025` | 20261025 | NÃO MESCLADA — 2 commit(s) à frente |2026-10-26T01:41:09Z — RECENTE |
| `feat/agro-live-probe-temporario-20261025` | 20261025 | NÃO MESCLADA — 3 commit(s) à frente |2026-10-26T01:23:24Z — RECENTE |
| `feat/agro-staging-replay-gcs-20261023` | 20261023 | NÃO MESCLADA — 4 commit(s) à frente |2026-10-23T19:07:42Z — RECENTE |
| `feat/agrobr-comex-cftc-ledger-20261026` | 20261026 | NÃO MESCLADA — 5 commit(s) à frente |2026-10-26T15:12:48Z — RECENTE |
| `feat/antaq-aquarela-nova-fonte-saude-20261025` | 20261025 | NÃO MESCLADA — 3 commit(s) à frente |2026-10-26T01:26:46Z — RECENTE |
| `feat/antaq-hf-metadata-source-size-audit-20261025` | 20261025 | NÃO MESCLADA — 3 commit(s) à frente |2026-10-26T01:29:56Z — RECENTE |
| `feat/antaq-hidrovia-derivada-2025-bq-20261025` | 20261025 | NÃO MESCLADA — 3 commit(s) à frente |2026-10-26T01:10:35Z — RECENTE |
| `feat/antaq-hidrovia-produtos-20261023` | 20261023 | NÃO MESCLADA — 14 commit(s) à frente |2026-10-23T11:50:49Z — MAIS DE 3 DIAS |
| `feat/antaq-historico-qualidade-lineup-20261019` | 20261019 | NÃO MESCLADA — 231 commit(s) à frente |2026-10-20T02:34:36Z — MAIS DE 3 DIAS |
| `feat/antaq-monitor-disponibilidade-20261023` | 20261023 | NÃO MESCLADA — 6 commit(s) à frente |2026-10-23T12:13:49Z — MAIS DE 3 DIAS |
| `feat/antt-2025-readonly-gcp-20261023` | 20261023 | NÃO MESCLADA — 2 commit(s) à frente |2026-10-23T17:51:29Z — RECENTE |
| `feat/antt-2026-primeira-carga-unica-gcp-20261023` | 20261023 | NÃO MESCLADA — 3 commit(s) à frente |2026-10-23T16:01:18Z — MAIS DE 3 DIAS |
| `feat/antt-anuario-rgi-20261023` | 20261023 | NÃO MESCLADA — 15 commit(s) à frente |2026-10-23T11:22:44Z — MAIS DE 3 DIAS |
| `feat/antt-auditoria-historico-bq-21anos-20261023` | 20261023 | NÃO MESCLADA — 4 commit(s) à frente |2026-10-23T18:11:51Z — RECENTE |
| `feat/antt-backfill-2006-2021-cargas-limitadas-20261023` | 20261023 | NÃO MESCLADA — 1 commit(s) à frente |2026-10-23T17:56:35Z — RECENTE |
| `feat/antt-backfill-2022-2025-gcp-20261023` | 20261023 | NÃO MESCLADA — 5 commit(s) à frente |2026-10-23T17:51:21Z — RECENTE |
| `feat/antt-mdfe-volumes-od-20261022` | 20261022 | NÃO MESCLADA — 16 commit(s) à frente |2026-10-23T03:24:57Z — MAIS DE 3 DIAS |
| `feat/antt-piloto-gcp-preparacao-20261023` | 20261023 | NÃO MESCLADA — 4 commit(s) à frente |2026-10-23T15:50:55Z — MAIS DE 3 DIAS |
| `feat/antt-rgi-gcp-rebased-20261023` | 20261023 | NÃO MESCLADA — 3 commit(s) à frente |2026-10-23T19:06:22Z — RECENTE |
| `feat/antt-rgi-rodovia-gcp-top16-20261023` | 20261023 | NÃO MESCLADA — 4 commit(s) à frente |2026-10-23T19:03:57Z — RECENTE |
| `feat/antt-vigia-revisoes-gcp-20261023` | 20261023 | NÃO MESCLADA — 4 commit(s) à frente |2026-10-23T19:04:39Z — RECENTE |
| `feat/apis-flood-ensemble-fao-fpma-20261021` | 20261021 | NÃO MESCLADA — 459 commit(s) à frente |2026-10-21T21:15:31Z — MAIS DE 3 DIAS |
| `feat/argentina-magyp-live-evidencia` | sem data | NÃO MESCLADA — 2 commit(s) à frente |2026-10-26T01:54:48Z — RECENTE |
| `feat/bcb-focus-expectativas-20261021` | 20261021 | NÃO MESCLADA — 449 commit(s) à frente |2026-10-21T19:42:41Z — MAIS DE 3 DIAS |
| `feat/bcb-sgs11-gcp-main-20261023` | 20261023 | NÃO MESCLADA — 5 commit(s) à frente |2026-10-23T17:58:53Z — RECENTE |
| `feat/bibliotecas-coleta-avancada-20261026` | 20261026 | NÃO MESCLADA — 4 commit(s) à frente |2026-10-26T15:40:03Z — RECENTE |
| `feat/bootstrap-acessos-protegidos-main-20261021` | 20261021 | MESCLADA — ancestral da main |2026-10-21T17:42:23Z — MAIS DE 3 DIAS |
| `feat/bootstrap-duas-tabelas-gcp-20261023` | 20261023 | NÃO MESCLADA — 4 commit(s) à frente |2026-10-23T19:00:07Z — RECENTE |
| `feat/brasilapi-refs-nivon-20261021` | 20261021 | NÃO MESCLADA — 443 commit(s) à frente |2026-10-21T17:30:50Z — MAIS DE 3 DIAS |
| `feat/catalogo-fontes-gratuitas-20261021` | 20261021 | NÃO MESCLADA — 451 commit(s) à frente |2026-10-21T18:30:55Z — MAIS DE 3 DIAS |
| `feat/coleta-gcp-nucleo-main-20261023` | 20261023 | NÃO MESCLADA — 26 commit(s) à frente |2026-10-23T11:31:18Z — MAIS DE 3 DIAS |
| `feat/coleta-real-camadas-20261022` | 20261022 | NÃO MESCLADA — 629 commit(s) à frente |2026-10-23T11:25:34Z — MAIS DE 3 DIAS |
| `feat/coletores-apis-gratuitas-reais-20261021` | 20261021 | NÃO MESCLADA — 447 commit(s) à frente |2026-10-21T19:18:00Z — MAIS DE 3 DIAS |
| `feat/conectores-gcp-conab-sgs-20261023` | 20261023 | NÃO MESCLADA — 658 commit(s) à frente |2026-10-23T15:52:37Z — MAIS DE 3 DIAS |
| `feat/conectores-google-cloud-lote1-20261023` | 20261023 | NÃO MESCLADA — 628 commit(s) à frente |2026-10-23T11:52:18Z — MAIS DE 3 DIAS |
| `feat/connectores-gtr-noaa-pinksheet-geodata-20261021` | 20261021 | NÃO MESCLADA — 459 commit(s) à frente |2026-10-21T20:43:46Z — MAIS DE 3 DIAS |
| `feat/connectores-publicos-inpe-cftc-antt-20261021` | 20261021 | NÃO MESCLADA — 450 commit(s) à frente |2026-10-21T19:37:23Z — MAIS DE 3 DIAS |
| `feat/consulta-analitica-bq-fontes-20261023` | 20261023 | NÃO MESCLADA — 3 commit(s) à frente |2026-10-23T12:17:22Z — MAIS DE 3 DIAS |
| `feat/corredores-ferrovia-historico-21anos-bq-20261023` | 20261023 | NÃO MESCLADA — 2 commit(s) à frente |2026-10-23T18:15:40Z — RECENTE |
| `feat/corredores-ferroviarios-estacoes-20261023` | 20261023 | NÃO MESCLADA — 14 commit(s) à frente |2026-10-23T12:19:55Z — MAIS DE 3 DIAS |
| `feat/corredores-primeira-view-bq-real-20261023` | 20261023 | NÃO MESCLADA — 1 commit(s) à frente |2026-10-23T16:06:52Z — MAIS DE 3 DIAS |
| `feat/earthsearch-usda-gtr-bases-20261021` | 20261021 | NÃO MESCLADA — 453 commit(s) à frente |2026-10-21T20:28:56Z — MAIS DE 3 DIAS |
| `feat/eurostat-faostat-qcl-api-20261021` | 20261021 | NÃO MESCLADA — 460 commit(s) à frente |2026-10-21T23:00:48Z — MAIS DE 3 DIAS |
| `feat/expansao-50-fontes-20261022` | 20261022 | NÃO MESCLADA — 549 commit(s) à frente |2026-10-23T11:26:41Z — MAIS DE 3 DIAS |
| `feat/faostat-bulk-manifest-20261021` | 20261021 | NÃO MESCLADA — 460 commit(s) à frente |2026-10-21T23:06:48Z — MAIS DE 3 DIAS |
| `feat/faostat-qcl-bigquery-contract-20261021` | 20261021 | NÃO MESCLADA — 464 commit(s) à frente |2026-10-22T00:23:17Z — MAIS DE 3 DIAS |
| `feat/faostat-qcl-stream-sqlite-20261021` | 20261021 | NÃO MESCLADA — 461 commit(s) à frente |2026-10-22T00:15:31Z — MAIS DE 3 DIAS |
| `feat/fontes-complementares-glam-wapor-portwatch-20261021` | 20261021 | NÃO MESCLADA — 453 commit(s) à frente |2026-10-21T20:07:55Z — MAIS DE 3 DIAS |
| `feat/fontes-ibge-worldbank-operacionais-20261023` | 20261023 | NÃO MESCLADA — 16 commit(s) à frente |2026-10-23T15:56:48Z — MAIS DE 3 DIAS |
| `feat/gcp-ativacao-carga-integrada-20261025` | 20261025 | NÃO MESCLADA — 6 commit(s) à frente |2026-10-26T01:29:03Z — RECENTE |
| `feat/gcp-bootstrap-tabelas-consolidadas-20261023` | 20261023 | NÃO MESCLADA — 5 commit(s) à frente |2026-10-23T18:06:24Z — RECENTE |
| `feat/gcp-main-integracao-resiliente-20261023` | 20261023 | NÃO MESCLADA — 62 commit(s) à frente |2026-10-23T17:49:07Z — RECENTE |
| `feat/gcp-preflight-iam-readonly-20261023` | 20261023 | NÃO MESCLADA — 3 commit(s) à frente |2026-10-23T17:53:12Z — RECENTE |
| `feat/gcp-readonly-infra-audit-20261023` | 20261023 | NÃO MESCLADA — 4 commit(s) à frente |2026-10-23T17:58:43Z — RECENTE |
| `feat/gcp-wif-smoke-leitura-20261023` | 20261023 | NÃO MESCLADA — 3 commit(s) à frente |2026-10-23T15:40:57Z — MAIS DE 3 DIAS |
| `feat/go-live-portal-interno-20261025` | 20261025 | MESCLADA — ancestral da main |2026-10-26T02:48:37Z — RECENTE |
| `feat/go-live-terminal-interno-20261025` | 20261025 | NÃO MESCLADA — 11 commit(s) à frente |2026-10-26T02:07:21Z — RECENTE |
| `feat/go-live-terminal-leitura-20261025` | 20261025 | NÃO MESCLADA — 2 commit(s) à frente |2026-10-26T02:04:54Z — RECENTE |
| `feat/go-live-terminal-ptax-gcp-20261025` | 20261025 | NÃO MESCLADA — 11 commit(s) à frente |2026-10-26T03:12:19Z — RECENTE |
| `feat/hidromet-fontes-publicas-power-glofas-20261021` | 20261021 | MESCLADA — ancestral da main |2026-10-21T20:44:19Z — MAIS DE 3 DIAS |
| `feat/integracoes-ia-p0-p2-optin-20261026` | 20261026 | NÃO MESCLADA — 1 commit(s) à frente |2026-10-26T13:15:12Z — RECENTE |
| `feat/integracoes-lineup-nacional-20261019` | 20261019 | NÃO MESCLADA — 216 commit(s) à frente |2026-10-19T23:46:39Z — MAIS DE 3 DIAS |
| `feat/inteligencia-corredores-intermodais-20261023` | 20261023 | NÃO MESCLADA — 7 commit(s) à frente |2026-10-23T11:45:58Z — MAIS DE 3 DIAS |
| `feat/ivo-cerebro-historico-20261019` | 20261019 | NÃO MESCLADA — 226 commit(s) à frente |2026-10-20T02:30:36Z — MAIS DE 3 DIAS |
| `feat/lineup-itaqui-codeba-20261019` | 20261019 | NÃO MESCLADA — 212 commit(s) à frente |2026-10-19T23:51:40Z — MAIS DE 3 DIAS |
| `feat/maritimo-cloudrun-deploy-seguro-20261023` | 20261023 | NÃO MESCLADA — 2 commit(s) à frente |2026-10-23T19:09:56Z — RECENTE |
| `feat/maritimo-gcp-esquema-real-20261023` | 20261023 | NÃO MESCLADA — 1 commit(s) à frente |2026-10-23T17:57:58Z — RECENTE |
| `feat/maritimo-gcp-primeira-coleta-real-20261023` | 20261023 | NÃO MESCLADA — 2 commit(s) à frente |2026-10-23T18:05:02Z — RECENTE |
| `feat/maritimo-gcp-principal-20261023` | 20261023 | NÃO MESCLADA — 1 commit(s) à frente |2026-10-23T17:49:55Z — RECENTE |
| `feat/maritimo-go-live-gha-6h-20261025` | 20261025 | NÃO MESCLADA — 1 commit(s) à frente |2026-10-26T01:57:21Z — RECENTE |
| `feat/maritimo-preflight-main-20261023` | 20261023 | NÃO MESCLADA — 2 commit(s) à frente |2026-10-23T17:54:47Z — RECENTE |
| `feat/maritimo-scheduler-seguro-20261025` | 20261025 | NÃO MESCLADA — 2 commit(s) à frente |2026-10-26T01:23:42Z — RECENTE |
| `feat/mercado-bcb-portal-existente-20261025` | 20261025 | NÃO MESCLADA — 9 commit(s) à frente |2026-10-26T02:18:53Z — RECENTE |
| `feat/meteo-publica-inmet-cptec-20261021` | 20261021 | MESCLADA — ancestral da main |2026-10-21T20:51:34Z — MAIS DE 3 DIAS |
| `feat/migracao-neon-para-gcp-20261023` | 20261023 | NÃO MESCLADA — 12 commit(s) à frente |2026-10-23T12:21:15Z — MAIS DE 3 DIAS |
| `feat/nivon-ais-geocercas-evidencia-inferida-20261025` | 20261025 | MESCLADA — ancestral da main |2026-10-26T01:32:08Z — RECENTE |
| `feat/nivon-ais-ledger-replay-e2e-20261025` | 20261025 | MESCLADA — ancestral da main |2026-10-26T01:25:48Z — RECENTE |
| `feat/nivon-catalogo-total-github-20261026` | 20261026 | NÃO MESCLADA — 7 commit(s) à frente |2026-10-26T15:29:29Z — RECENTE |
| `feat/nivon-go-live-painel-interno-gcs-20261025` | 20261025 | MESCLADA — ancestral da main |2026-10-26T02:06:48Z — RECENTE |
| `feat/nivon-go-live-rotina-dias-uteis-20261025` | 20261025 | MESCLADA — ancestral da main |2026-10-26T02:09:03Z — RECENTE |
| `feat/nivon-ia-evidencias-ci-20261026` | 20261026 | NÃO MESCLADA — 4 commit(s) à frente |2026-10-26T14:16:19Z — RECENTE |
| `feat/nivon-ia-pilotos-operacionais-20261026` | 20261026 | NÃO MESCLADA — 7 commit(s) à frente |2026-10-26T14:42:59Z — RECENTE |
| `feat/nivon-maritime-readonly-bigquery-panel-20261023` | 20261023 | MESCLADA — ancestral da main |2026-10-23T19:05:28Z — RECENTE |
| `feat/nivon-painel-integrado-logistica-maritimo-quant-20261023` | 20261023 | MESCLADA — ancestral da main |2026-10-23T17:59:08Z — RECENTE |
| `feat/nivon-terminal-interno-golive-20261025` | 20261025 | NÃO MESCLADA — 9 commit(s) à frente |2026-10-26T02:05:57Z — RECENTE |
| `feat/nivon-terminal-privado-go-live-20261025` | 20261025 | NÃO MESCLADA — 9 commit(s) à frente |2026-10-26T02:03:59Z — RECENTE |
| `feat/nivon-terminal-web-go-live-20261025` | 20261025 | NÃO MESCLADA — 6 commit(s) à frente |2026-10-26T02:05:05Z — RECENTE |
| `feat/nivon-web-mvp-real-20261025` | 20261025 | NÃO MESCLADA — 6 commit(s) à frente |2026-10-26T02:06:52Z — RECENTE |
| `feat/painel-trimodal-2025-fonte-hidrovia-isolada-20261025` | 20261025 | NÃO MESCLADA — 3 commit(s) à frente |2026-10-26T01:36:59Z — RECENTE |
| `feat/piloto-gcp-wdi-e2e-20261023` | 20261023 | NÃO MESCLADA — 6 commit(s) à frente |2026-10-23T19:05:44Z — RECENTE |
| `feat/portal-gcs-cloudrun-privado-20261025` | 20261025 | MESCLADA — ancestral da main |2026-10-26T03:04:00Z — RECENTE |
| `feat/preflight-golive-cloudrun-20261025` | 20261025 | NÃO MESCLADA — 5 commit(s) à frente |2026-10-26T02:48:52Z — RECENTE |
| `feat/prova-real-sgs-gcp-fontes-20261023` | 20261023 | NÃO MESCLADA — 3 commit(s) à frente |2026-10-23T19:00:37Z — RECENTE |
| `feat/ptax-bcb-agendamento-wif-escritor-unico-20261023` | 20261023 | NÃO MESCLADA — 4 commit(s) à frente |2026-10-23T12:44:05Z — MAIS DE 3 DIAS |
| `feat/series-corredores-antt-bigquery-20261023` | 20261023 | NÃO MESCLADA — 7 commit(s) à frente |2026-10-23T12:44:17Z — MAIS DE 3 DIAS |
| `feat/sisfogo-roi-fonte-oficial-20261021` | 20261021 | NÃO MESCLADA — 445 commit(s) à frente |2026-10-21T18:18:12Z — MAIS DE 3 DIAS |
| `feat/soilgrids-embrapa-solos-20261021` | 20261021 | NÃO MESCLADA — 449 commit(s) à frente |2026-10-21T19:48:40Z — MAIS DE 3 DIAS |
| `feat/terminal-gcs-dados-reais-unificado-20261025` | 20261025 | NÃO MESCLADA — 8 commit(s) à frente |2026-10-26T03:03:41Z — RECENTE |
| `feat/terminal-nivon-go-live-visao-publica-20261025` | 20261025 | NÃO MESCLADA — 1 commit(s) à frente |2026-10-26T02:06:54Z — RECENTE |
| `feat/verificacao-cloud-gcp-20261023` | 20261023 | NÃO MESCLADA — 5 commit(s) à frente |2026-10-23T12:12:16Z — MAIS DE 3 DIAS |
| `feat/visao-multimodal-anttrgi-ferrovia-2025-20261023` | 20261023 | NÃO MESCLADA — 5 commit(s) à frente |2026-10-23T19:20:06Z — RECENTE |
| `feature/nivon-anp-ppi-direto-20261026` | 20261026 | NÃO MESCLADA — 7 commit(s) à frente |2026-10-26T14:39:37Z — RECENTE |
| `feature/transporte-antt-antaq-20261022` | 20261022 | NÃO MESCLADA — 50 commit(s) à frente |2026-10-23T11:34:51Z — MAIS DE 3 DIAS |
| `fix/agro-http-seguro-e-bq-custo-20261023` | 20261023 | NÃO MESCLADA — 4 commit(s) à frente |2026-10-23T19:03:26Z — RECENTE |
| `fix/antaq-hf-cache-inspecao-estrita-20261025` | 20261025 | NÃO MESCLADA — 3 commit(s) à frente |2026-10-26T01:23:10Z — RECENTE |
| `fix/antaq-hf-cache-realpath-20261025` | 20261025 | NÃO MESCLADA — 3 commit(s) à frente |2026-10-26T01:16:38Z — RECENTE |
| `fix/antaq-hf-revision-file-size-pinned-20261025` | 20261025 | MESCLADA — ancestral da main |2026-10-26T01:30:44Z — RECENTE |
| `fix/antaq-hf-staging-manual-20261025` | 20261025 | NÃO MESCLADA — 3 commit(s) à frente |2026-10-26T01:21:56Z — RECENTE |
| `fix/antaq-parquet-cache-staging-safe-20261025` | 20261025 | NÃO MESCLADA — 6 commit(s) à frente |2026-10-26T01:28:10Z — RECENTE |
| `fix/antaq-replica-manual-isolada-20261025` | 20261025 | NÃO MESCLADA — 2 commit(s) à frente |2026-10-26T01:20:10Z — RECENTE |
| `fix/antt-2025-inspecao-schema-20261023` | 20261023 | NÃO MESCLADA — 1 commit(s) à frente |2026-10-23T17:54:36Z — RECENTE |
| `fix/antt-backfill-manual-gates-20261023` | 20261023 | NÃO MESCLADA — 3 commit(s) à frente |2026-10-23T17:58:01Z — RECENTE |
| `fix/antt-bq-readiness-20261023` | 20261023 | NÃO MESCLADA — 6 commit(s) à frente |2026-10-23T15:49:41Z — MAIS DE 3 DIAS |
| `fix/antt-ckan-fallback-verificado-20261023` | 20261023 | NÃO MESCLADA — 3 commit(s) à frente |2026-10-23T15:55:01Z — MAIS DE 3 DIAS |
| `fix/antt-ckan-historico-provas-sha-20261023` | 20261023 | NÃO MESCLADA — 8 commit(s) à frente |2026-10-23T18:07:58Z — RECENTE |
| `fix/antt-ckan-retry-20261023` | 20261023 | NÃO MESCLADA — 3 commit(s) à frente |2026-10-23T11:38:39Z — MAIS DE 3 DIAS |
| `fix/antt-fallback-csv-oficial-20261023` | 20261023 | NÃO MESCLADA — 4 commit(s) à frente |2026-10-23T15:56:34Z — MAIS DE 3 DIAS |
| `fix/antt-gcp-precise-gates-20261023` | 20261023 | NÃO MESCLADA — 3 commit(s) à frente |2026-10-23T15:53:07Z — MAIS DE 3 DIAS |
| `fix/antt-gcp-unificar-config-20261023` | 20261023 | NÃO MESCLADA — 8 commit(s) à frente |2026-10-23T12:06:44Z — MAIS DE 3 DIAS |
| `fix/antt-piloto-manual-unico-20261023` | 20261023 | NÃO MESCLADA — 5 commit(s) à frente |2026-10-23T17:49:03Z — RECENTE |
| `fix/antt-piloto-sem-reexecucao-automatica-20261023` | 20261023 | NÃO MESCLADA — 3 commit(s) à frente |2026-10-23T17:49:43Z — RECENTE |
| `fix/antt-rgi-gcp-google-api-notfound-20261023` | 20261023 | NÃO MESCLADA — 1 commit(s) à frente |2026-10-23T19:08:55Z — RECENTE |
| `fix/antt-rgi-smoke-main-20261023` | 20261023 | NÃO MESCLADA — 1 commit(s) à frente |2026-10-23T11:26:25Z — MAIS DE 3 DIAS |
| `fix/antt-vigia-fonte-indisponivel-20261023` | 20261023 | NÃO MESCLADA — 3 commit(s) à frente |2026-10-23T19:11:59Z — RECENTE |
| `fix/antt-vigia-retry-fonte-20261023` | 20261023 | NÃO MESCLADA — 2 commit(s) à frente |2026-10-23T19:08:18Z — RECENTE |
| `fix/auditoria-gcp-diaria-sem-escrita-20261023` | 20261023 | NÃO MESCLADA — 2 commit(s) à frente |2026-10-23T19:09:09Z — RECENTE |
| `fix/bigquery-merge-particoes-custo-20261023` | 20261023 | NÃO MESCLADA — 5 commit(s) à frente |2026-10-23T17:53:41Z — RECENTE |
| `fix/cepea-estado-ledger-verificado-20261025` | 20261025 | NÃO MESCLADA — 4 commit(s) à frente |2026-10-26T01:28:32Z — RECENTE |
| `fix/formatos-reais-noaa-gtr-wb-esa-20261021` | 20261021 | NÃO MESCLADA — 453 commit(s) à frente |2026-10-21T20:53:15Z — MAIS DE 3 DIAS |
| `fix/gcp-auditoria-estado-por-tabela-20261025` | 20261025 | NÃO MESCLADA — 1 commit(s) à frente |2026-10-26T01:25:52Z — RECENTE |
| `fix/gcp-auditoria-schema-integral-20261025` | 20261025 | NÃO MESCLADA — 5 commit(s) à frente |2026-10-26T01:22:46Z — RECENTE |
| `fix/gcp-preflight-particao-e-regiao-20261023` | 20261023 | NÃO MESCLADA — 2 commit(s) à frente |2026-10-23T17:57:27Z — RECENTE |
| `fix/gcp-provider-canonico-migracoes-20261023` | 20261023 | NÃO MESCLADA — 12 commit(s) à frente |2026-10-23T17:55:42Z — RECENTE |
| `fix/gcp-regiao-inventario-destinos-20261023` | 20261023 | NÃO MESCLADA — 1 commit(s) à frente |2026-10-23T15:52:35Z — MAIS DE 3 DIAS |
| `fix/go-live-cloudrun-authenticated-acceptance-20261025` | 20261025 | NÃO MESCLADA — 3 commit(s) à frente |2026-10-26T03:10:08Z — RECENTE |
| `fix/go-live-controlar-gcp-execucoes-20261025` | 20261025 | MESCLADA — ancestral da main |2026-10-26T02:53:28Z — RECENTE |
| `fix/go-live-descoberta-recursos-existentes-20261025` | 20261025 | NÃO MESCLADA — 4 commit(s) à frente |2026-10-26T02:57:28Z — RECENTE |
| `fix/go-live-estado-bloqueios-log-20261025` | 20261025 | NÃO MESCLADA — 1 commit(s) à frente |2026-10-26T03:01:13Z — RECENTE |
| `fix/go-live-terminal-container-e2e-20261025` | 20261025 | NÃO MESCLADA — 2 commit(s) à frente |2026-10-26T02:55:06Z — RECENTE |
| `fix/golive-gate-sha-atual-e-preflight-20261025` | 20261025 | NÃO MESCLADA — 3 commit(s) à frente |2026-10-26T02:09:38Z — RECENTE |
| `fix/golive-gate-smoke-auth-20261025` | 20261025 | NÃO MESCLADA — 9 commit(s) à frente |2026-10-26T03:07:09Z — RECENTE |
| `fix/golive-p0-piloto-gcp-20261025` | 20261025 | NÃO MESCLADA — 6 commit(s) à frente |2026-10-26T03:02:51Z — RECENTE |
| `fix/golive-readonly-staging-opcional-20261025` | 20261025 | MESCLADA — ancestral da main |2026-10-26T02:57:23Z — RECENTE |
| `fix/monitor-p0-main-codigo-atual-20261023` | 20261023 | NÃO MESCLADA — 4 commit(s) à frente |2026-10-23T19:05:29Z — RECENTE |
| `fix/nivon-gcp-migracao-controle-operacional-20261023` | 20261023 | NÃO MESCLADA — 2 commit(s) à frente |2026-10-23T12:40:07Z — MAIS DE 3 DIAS |
| `fix/nivon-go-live-gcs-append-only-20261025` | 20261025 | MESCLADA — ancestral da main |2026-10-26T02:12:10Z — RECENTE |
| `fix/noaa-mei-missing-sentinel-20261021` | 20261021 | NÃO MESCLADA — 450 commit(s) à frente |2026-10-21T20:55:54Z — MAIS DE 3 DIAS |
| `fix/open-meteo-ensemble-control-20261021` | 20261021 | NÃO MESCLADA — 453 commit(s) à frente |2026-10-21T21:21:54Z — MAIS DE 3 DIAS |
| `fix/p0-antt-rgi-ci-separado-20261023` | 20261023 | NÃO MESCLADA — 5 commit(s) à frente |2026-10-23T12:22:42Z — MAIS DE 3 DIAS |
| `fix/ptax-ponte-ci-isolada-diagnostico-http-20261025` | 20261025 | NÃO MESCLADA — 3 commit(s) à frente |2026-10-26T01:23:22Z — RECENTE |
| `fix/workflow-inmet-runner-context-20261021` | 20261021 | MESCLADA — ancestral da main |2026-10-21T18:26:54Z — MAIS DE 3 DIAS |
| `integration/base-gcp-coletor-20261023` | 20261023 | NÃO MESCLADA — 632 commit(s) à frente |2026-10-23T11:55:32Z — MAIS DE 3 DIAS |
| `release/nivon-go-live-conab-20261025` | 20261025 | NÃO MESCLADA — 15 commit(s) à frente |2026-10-26T02:10:33Z — RECENTE |
| `release/nivon-go-live-interno-gates-20261025` | 20261025 | NÃO MESCLADA — 7 commit(s) à frente |2026-10-26T03:03:08Z — RECENTE |
| `release/ptax-mainline-go-live-20261025` | 20261025 | NÃO MESCLADA — 10 commit(s) à frente |2026-10-26T03:04:18Z — RECENTE |
| `release/terminal-privado-aceite-live-20261025` | 20261025 | NÃO MESCLADA — 7 commit(s) à frente |2026-10-26T03:00:08Z — RECENTE |
| `release/validacao-terminal-privado-20261025` | 20261025 | NÃO MESCLADA — 4 commit(s) à frente |2026-10-26T02:59:41Z — RECENTE |
| `review/nivon-ciencia-base-20261019` | 20261019 | NÃO MESCLADA — 238 commit(s) à frente |2026-10-20T02:47:43Z — MAIS DE 3 DIAS |
| `test/qa-faostat-qcl-zip-once-20261021` | 20261021 | NÃO MESCLADA — 458 commit(s) à frente |2026-10-22T00:17:10Z — MAIS DE 3 DIAS |
| `test/smoke-eurostat-faostat-qcl-20261021` | 20261021 | NÃO MESCLADA — 456 commit(s) à frente |2026-10-21T23:07:54Z — MAIS DE 3 DIAS |
| `test/smoke-flood-ensemble-fpma-20261021` | 20261021 | NÃO MESCLADA — 456 commit(s) à frente |2026-10-21T21:22:55Z — MAIS DE 3 DIAS |
| `test/smoke-fontes-publicas-20261021` | 20261021 | NÃO MESCLADA — 455 commit(s) à frente |2026-10-21T20:57:00Z — MAIS DE 3 DIAS |
| `tmp/ptax-fastlane-reconcile-20261025` | 20261025 | NÃO MESCLADA — 10 commit(s) à frente |2026-10-26T03:09:42Z — RECENTE |

## Decisão solicitada ao proprietário (após auditoria conclusiva)

1. Revisar a lista comprovada de branches mescladas e abandonadas.
2. Autorizar expressamente `APROVADO` para a exclusão **apenas** do conjunto apresentado.
3. Ativar GitHub → **Settings → General → Pull Requests → Automatically delete head branches** para apagar automaticamente a branch de PR após futuros merges (não elimina branches antigas sem PR).
