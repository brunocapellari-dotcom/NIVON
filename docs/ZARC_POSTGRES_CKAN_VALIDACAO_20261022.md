# NIVON — PostgreSQL de teste e sinais reais de versão do ZARC

Corte técnico: **22/10/2026 no horário de Mato Grosso**, execuções GitHub Actions em 23/10 UTC.

## 1. Banco real de teste, dados fictícios

- DDL: `sql/postgres/002_zarc_mt_staging.sql` (aplicado apenas a contêiner PostgreSQL 17 descartável do runner).
- Código: `src/nivon/zarc_pg_loader_teste.py` (somente servidor `localhost`/`127.0.0.1`/`::1`, sem autocommit, `executar=True`, origem `SINTETICO`).
- Orquestração: `scripts/ensaio_zarc_postgres_local.py`, acionada por `.github/workflows/ensaio-zarc-postgres-local.yml`.
- [Execução #39892330078](https://github.com/brunocapellari-dotcom/NIVON/actions/runs/39892330078) **PASSOU**: 27.918 linhas **fictícias**, 27.918 hashes/conteúdos verificados após gravação, 1 edição, 2 coletas, replay de 27.918 linhas sem duplicação e transação completa, execução 20,481 segundos.
- A conexão PostgreSQL foi efetiva, mas exclusivamente em serviço Docker local ao job efêmero. **Não houve acesso a Neon, Oracle, BigQuery, banco agrícola nem fonte real nessa execução**.
- `tests/test_zarc_pg_loader_teste.py` bloqueia execução sem opt-in, hosts externos, autocommit e lotes maiores que 500.
- Não copiar a senha fictícia do contêiner para produção; o loader de teste não é cliente de produção e nunca deve conectar a banco externo.

## 2. Catálogo oficial CKAN como sinal de atualização

- Fontes oficiais: https://dados.agricultura.gov.br/dataset/6d3d141c-885e-41a4-ab7f-dc8ff323b96f e https://dados.agricultura.gov.br/pt_BR/dataset/tabua-de-risco-zoneamento-agricola-de-risco-climatico/resource/139e5a60-1f43-4cc8-aeab-a35dbbf816c0
- `src/nivon/fontes_abertas_lote.py`: agora preserva `revision_id` do pacote e de cada recurso; `src/nivon/zarc_sinais_ckan.py`: valida fonte, licença e recurso oficial; registra em SQLite local as observações temporais e hash dos metadados.
- `scripts/diagnostico_zarc_ckan_live.py` e workflow `verificar-zarc-ckan.yml` (somente uma consulta de metadados, sem download do CSV).
- [Execução #39892626092](https://github.com/brunocapellari-dotcom/NIVON/actions/runs/39892626092) **PASSOU**:
  - Dataset ZARC_JANELAS, recurso `139e5a60-1f43-4cc8-aeab-a35dbbf816c0`.
  - Licença CKAN declarada: `cc-by` (**atribuição ao MAPA é condição de uso**).
  - Revisão do conjunto: `ba9ffb46-f96f-4fab-a7af-b157b2ac3c67`.
  - Revisão do recurso: `23321f88-93a2-4c8f-b956-27d83f6d84f6`.
  - Campo CKAN `metadata_modified`: `2026-10-22T07:12:04.727006`.
  - Campo CKAN `last_modified` do recurso: `2026-10-22T07:11:39.145569`.
  - Coletado em: `2026-10-23T03:00:18.102438+00:00`.
  - SHA-256 dos metadados normalizados: `a96f4fb03cb44364af7b0df4f12ba9d22eef86c127b0cfbe31a83066c9832931`.
- Estas datas CKAN não têm offset declarado no payload: **não imputar timezone ou tratá-las como instante de publicação de cada Portaria**.
- `revision_id` indica mudança de metadados/recurso catalogado, **NÃO comprova que os bytes do CSV mudaram**. O único identificador de versão de conteúdo é SHA-256 do próprio CSV, medido após baixar a edição autorizada.
- Referência de comparação de conteúdo anterior: execução #39854814268, SHA-256 integral `65f52578a4869894311888323d87db75a5452829a3dabef90786f3f14b02d652`, 211.652.014 bytes e 27.918 registros MT naquele momento. Ainda não há prova de que a edição atual possua o mesmo SHA: requer nova coleta completa e verificação.
- `zarc_sinais_ckan.py` registra observações localmente e calcula mudança de metadados contra coletas anteriores. A execução online de 23/10 utilizou SQLite temporário; **não representa vigilância agendada com memória durável**.

## 3. Controles que permanecem ativos

- Catálogo canônico exige `enabled=false`, `collection_authorized=false` de todos os datasets; não desativamos nem burlamos esse gate para ingerir fonte real.
- Rota `ZARC_JANELAS` preserva `runtime_enabled=false`, `scheduled_enabled=false`.
- A licença pública é evidência de direito de uso com atribuição, mas ainda falta implementação formal da atribuição nos produtos, revisão das condições aplicáveis ao fluxo e aprovação de armazenamento durável e destino agrícola.
- O arquivo CSV não foi anexado, commitado nem retido no runner. O PostgreSQL de teste foi destruído ao término da execução.
- Workflows de teste em runners públicos não criam contratos ou recursos de terceiros nesta etapa. Verificação de cotas e continuidade do ambiente operacional ainda é necessária.
- A migração para ambiente real requer escolha explícita de banco agrícola, controle de custos, backups e restauro, segregação de licenças, integridade e gates de publicação.

## Próximo incremento

Implementar retenção de marcos de CKAN em storage durável de baixo custo, automatização condicional sem baixar 211 MB diariamente e loader autorizado para staging agrícola, com circuito de permissões separado de relatórios. Não reutilizar projetos com nome PTAX nem simular dado real como sintético.
