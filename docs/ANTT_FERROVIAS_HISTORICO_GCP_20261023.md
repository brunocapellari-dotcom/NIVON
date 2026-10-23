# NIVON — Transporte ferroviario e hidroviario: prova E2E e ativacao GCP

**Data de execucao:** 23/10/2026. **PR:** #140 (rascunho, sem merge).  
**Objetivo:** conservar dados ferroviarios reais ANTT/SIADE, versionar revisoes e alimentar BigQuery; buscar acesso legal a dados brutos ANTAQ.

## Evidencia ANTT LIVE (nao no banco ainda)

- Historico 2006-2024: https://github.com/brunocapellari-dotcom/NIVON/actions/runs/39944237120
- Prova 2025 e 2026: https://github.com/brunocapellari-dotcom/NIVON/actions/runs/39895847815
- Testes do fluxo GCP com mocks, sem permissao IAM real: https://github.com/brunocapellari-dotcom/NIVON/actions/runs/39944971347

| Periodo | Registros OD | TU cumulativa | Situacao |
|---|---:|---:|---|
| 2006-2010 | 53.190 | 2.045.247.581 | PROVA LIVE |
| 2011-2015 | 39.599 | 2.316.979.435 | PROVA LIVE |
| 2016-2020 | 37.412 | 2.601.584.327 | PROVA LIVE, divergencias TU/TKU sinalizadas |
| 2021-2024 | 31.766 | 2.080.313.424 | PROVA LIVE, divergencias TU/TKU sinalizadas |
| **2006-2024** | **161.967** | **9.044.124.767** | SOMA HISTORICA, nao anual |
| 2025 | 7.802 | 555.077.765 | PROVA LIVE |
| 2026 jan-ago | 5.081 | 353.466.337 | PROVA LIVE |
| **2006-ago/2026** | **174.850** | **9.952.668.869** | SOMA DE 21 ANOS, ultimo parcial |

**Importante:** somas de eventos ferroviarios ao longo dos anos nao representam carga fisica unica. Nao somar volume rodoviario, ferroviario e hidroviario sem tratar transbordos. Dados publicados pela ANTT podem sofrer revisoes. 2025 da SIADE (555,078 milhoes TU) diverge do numero anteriormente citado pela CNT (554,48 milhoes); investigar recorte/data-base antes da homologacao.

### Arquivos e rastreabilidade

- `src/nivon/coleta_antt.py`: descobre recursos CKAN por ano, baixa, valida, gera manifesto SHA256 e JSONL em staging; arquivos brutos nao sao enviados ao GitHub.
- `src/nivon/transporte_multimodal.py`: parser CP1252/UTF-8, datas `MM_AA`/`MM/AAAA`, numeros brasileiros, TU/TKU separados e indicador `anomalia_tu_tku`.
- `src/nivon/resumo_antt.py`: agrega por ano/mes, ferrovia, mercadoria e UF, preservando as divergencias.
- `src/nivon/antt_gcs.py`: arquiva arquivos brutos em GCS imutavelmente pelo SHA; nao cria bucket.
- `src/nivon/antt_bigquery.py`: carga append-only, particao mensal por data_referencia, clustering ferrovia/mercadoria/UF, view `vw_antt_ferrovia_od_atual` com ultima versao por ano.
- `src/nivon/antt_gcp_pipeline.py`: um comando encadeia leitura HTTP, GCS e BigQuery, bloqueando a escrita analitica se GCS falhar.
- `.github/workflows/antt-ferrovia-gcp.yml`: preflight sem credenciais, WIF na main somente e coleta automatica ter/sex 12UTC depois de configurar as variaveis e integrar a PR. Cron no branch nao executa GCP.
- `.github/workflows/antt-ferrovia-backfill.yml`: prova historica em 4 lotes, artefatos resumo/manifesto retidos 90 dias. **Nao equivalem a armazenamento permanente no GCP.**

## Preparacao de identidade Google Cloud — nao realizada

Ativar somente com projeto, dataset e bucket existentes e apos verificar permissoes/custos.
No GitHub, em variaveis de repositorio (nao inserir chaves JSON), configurar:

- `NIVON_GCP_PROJECT_ID`: ID real do projeto.
- `NIVON_BQ_DATASET`: dataset existente.
- `NIVON_GCS_BUCKET`: bucket existente.
- `NIVON_GCP_WIF_PROVIDER`: provider de Workload Identity Federation existente e restrito ao repositorio **e branch main**.
- `NIVON_GCP_SERVICE_ACCOUNT`: service account dedicada, com acesso minimo ao bucket, dataset e criacao de jobs.

A conta deve ter permissoes para criar objetos **sem sobrescrever**, verificar metadados, criar tabela/view no dataset e executar BigQuery jobs. A WIF deve validar `repository` e `ref=refs/heads/main` para evitar OIDC de PRs ou forks. Nunca usar chave JSON de longa duracao como substituto por conveniencia. Ver https://docs.cloud.google.com/iam/docs/workload-identity-federation-with-deployment-pipelines.

**Estado atual:** repositorio verificado e os testes de contrato passaram. Credenciais GCP nao estao acessiveis por esta conversa, nao foram verificadas e nenhuma carga foi confirmada em GCS ou BigQuery. PR continua sem merge. O workflow de GCP executou somente preflight no branch sem IAM.

## ANTAQ — bloqueio externo

Fonte primaria dos volumes consolidados de 2025:
- https://www.gov.br/antaq/pt-br/central-de-conteudos/estudos-e-pesquisas-da-antaq-1/estudo-em-destaque
- https://www.gov.br/antaq/pt-br/central-de-conteudos/publicacoes-da-antaq/publicacoes-off/painel-estatistico-aquaviario-indisponivel

Indicadores de referencias nao aditivos: 91,3 Mi t navegacao interior estrita e aproximadamente 145 Mi t conjunto mais amplo das vias interiores, alem de 42,70 bi TKU de navegacao interior (indicador construido com distancias). A nova interface `aquarela.antaq.gov.br` foi identificada no menu da ANTAQ, mas o acesso consultado retornou HTTP 403; nao afirmar que oferece API/download publico. O formato ZIP/TXT de historico do EA nao foi validado em 23/10/2026. Manter #144 aberta e buscar canal oficial autorizado; nao automatizar contorno de Cloudflare.

## Proximos gates

1. Reconciliar 2025 ANTT e sinalizacoes TU/TKU; auditar conversao de unidades.
2. Confirmar dataset, bucket e WIF de Google Cloud com politica de IAM minima e custo.
3. Integrar a PR com controle de impacto sobre workflows paralelos ja presentes na main.
4. Executar primeira carga GCS+BigQuery real e consultar 2025/2026; registrar jobs e objetos, nao apenas mocks.
5. Retroalimentar 2006-2024 no mesmo pipeline mantendo hashes e revisoes.
6. Reativar ANTAQ apenas apos canal oficial de dados verificavel; integrar e testar volumes por hidrovia e tipo de navegacao.

**Status:** ANTT LIVE e historico **COMPROVADOS**; GCP **IMPLEMENTADO EM CODIGO, SEM EXECUCAO REAL**; ANTAQ detalhada **BLOQUEADA NA FONTE**.
