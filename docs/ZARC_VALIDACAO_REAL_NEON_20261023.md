# NIVON — ZARC real em quarentena, validação persistente (23/10/2026)

## Prova E2E real do arquivo oficial

Workflow: [#39944895765](https://github.com/brunocapellari-dotcom/NIVON/actions/runs/39944895765), iniciado em 23/10/2026 às 11:16 UTC e concluído com sucesso.

- CSV integral MAPA da safra 2026/2027: **211.652.014 bytes**
- SHA-256 original: `65f52578a4869894311888323d87db75a5452829a3dabef90786f3f14b02d652`
- Registros brasileiros no CSV: **957.490**
- Registros de Mato Grosso: **27.918**
- Municípios distintos identificados pelo geocódigo IBGE: **142**
- Licença CKAN em tempo real: `cc-by`, exigindo atribuição MAPA
- Novo revision_id no recurso: `2049227f-4c4c-46b5-b862-50c82be0e3d3`
- Hash do CKAN normalizado: `71370591c68687cd3fdcdc44fbb5364825add572c617265478992805baee58ea`
- Momento da coleta (UTC): `2026-10-23T11:16:17.393968+00:00`
- Hash integral idêntico ao observado na prova anterior, apesar da revisão CKAN **diferente**: significa que o conteúdo baixado é igual, **não** que os metadados não mudaram
- SQLite de quarentena e cofre RAW local processaram arquivo **real**, `PRAGMA integrity_check=ok`, FKs `OK`, total reconciliado, origem ledger `REAL_AUTORIZADO`
- Runner e arquivos locais foram descartados após a execução. O resultado **não** criou armazenamento RAW durável

## Permissão de coleta isolada

Novo `src/nivon/zarc_licenca_manual.py` permite somente **ZARC_JANELAS**, recurso oficial específico, licença `cc-by`, uma rodada manual com autorização explícita `consentimento_manual=True` e evidência SHA-256 dos metadados. Essa permissão é encaminhada ao `registro_snapshots.py` e `zarc_staging.py`.

O catálogo mantém os estados gerais `enabled=false`, `collection_authorized=false`, `runtime_enabled=false` e `scheduled_enabled=false`. O escopo manual **não** autoriza agendamento, publicação, comercialização de dados de terceiros, cálculos agronômicos ou escrita automática remota. Outros datasets continuam bloqueados.

Os testes sintéticos dessa funcionalidade executam gates e casos adversariais. A prova real acima executa a autorização manual após consultar metadados do próprio MAPA na mesma rodada.

## Banco agrícola persistente: o que foi gravado

Projeto Free Neon `NIVON-AGRO-DADOS` (`little-snow-10994610`, PostgreSQL 17, São Paulo, database `nivon_agro`).

Novos contratos executados:

- `sql/postgres/004_zarc_validacoes_arquivo.sql`: recebe uma linha de validação integral com SHA, contagens, proveniência GitHub, datas de coleta e campos obrigatoriamente `archived_to_private_bucket=false`, `rows_loaded_to_agro_database=false`, `approved_for_publication=false`. O banco **contém uma evidência real** do run #39944895765; não há nenhuma linha agrícola de CSV nessa tabela.
- `sql/postgres/005_zarc_estado_operacional.sql`: visão consultável que compara último sinal CKAN, revisão anterior, última validação real e quantidades de edições/linhas persistidas.
- Foi gravado segundo sinal CKAN da prova E2E real, com fingerprint e revision_id de 23/10; atualmente existem **2 observações** na tabela `zarc_ckan_sinais`.

Resultado da consulta à view `nivon_agro_staging.v_zarc_estado_operacional`:

- `revisao_ckan_mudou=true`, de `23321f88-93a2-4c8f-b956-27d83f6d84f6` para `2049227f-4c4c-46b5-b862-50c82be0e3d3`
- O arquivo original teve SHA idêntico ao anterior
- `mt_linhas_validadas_quarentena=27918`
- `edicoes_postgres=0`
- `linhas_mt_postgres=0`
- `arquivo_raw_arquivado=false`, `dados_reais_inseridos=false`, `liberado_publicacao=false`
- Estado: `VALIDACAO_REAL_CONCLUIDA_SEM_CARGA_DURAVEL`

## Bucket privado e bloqueio residual

Projeto Free Neon `NIVON-ARQUIVO-RAW` nos EUA, bucket `nivon-zarc-raw` privado. A listagem anterior confirmou **0 objetos**. Não foram inseridas credenciais no GitHub público.

O conector Neon fornece URLs pré-assinadas de PUT/GET, mas estas precisam ser recebidas pelo executor com segurança (por secret manager, identidade de workload ou integração segura). O acesso GitHub disponível neste contexto não tem ação para configurar GitHub Actions Secrets de modo seguro; não enviar URL assinada via arquivos do repositório, workflow_dispatch visível ou logs.

A compressão e verificação remotas estão codificadas em `zarc_neon_raw_upload.py`, mas **só foram testadas com transporte simulado**. Não declarar upload, restauração remota ou backup independente antes da prova real de GET + hash completo.

Após provisionar credenciais no executor e configurar política de acesso de gravação controlada, o próximo passo operacional é: coletar CSV oficial, calcular SHA, staging em quarentena, compactar Gzip determinístico e armazenar por `zarc/2026-2027/<sha>.csv.gz`, recuperar e revalidar, depois carregar e reconciliar 27.918 linhas no banco agrícola real. O número pode variar em revisões futuras.

## Distinção permanente de estados

**Dados reais lidos e validados = SIM.**

**Evidências da leitura real persistidas no Neon = SIM.**

**Arquivo original RAW no bucket = NÃO.**

**27.918 linhas ZARC carregadas no PostgreSQL persistente = NÃO.**

**Agendamento de atualização e publicação = NÃO.**

Não afirmar implantação produtiva do ZARC até completar armazenamento do RAW, carga durável, direitos por operação, interpretação agronômica e testes de recuperação.
