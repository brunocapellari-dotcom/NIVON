# NIVON — Plataforma de dados Google Cloud (decisão 21/10/2026)

**Decisão:** adotar Google Cloud como destino principal da infraestrutura de dados do NIVON, mantendo arquitetura portátil. **Estado: PLANEJADO; nenhum recurso GCP criado, nenhuma cobrança habilitada e nenhuma migração executada por esta PR.**

## 1. Estado de partida e condições

- A `main` contém o bootstrap protegido USDA, ANA e INMET, sem banco GCP.
- A PR #58 mantém PostgreSQL Neon PTAX real com `nivon_ptax_quotes`, `nivon_ptax_runs` e `nivon_ptax_checkpoints`; há execução histórica em andamento. Preservar Neon e seus dados, sem deletar nem parar triggers.
- A PR #61 e as branches de domínio possuem múltiplos módulos de persistência SQLite, ainda **não mesclados**. Reconciliar contratos e vintages antes de mover dados.
- Este documento é um contrato de preparação. `config/gcp_data_platform.v1.json` define `gcp_project_id: null`, serviços `enabled:false` e `paid_use_approved:false`.
- Cloud Run, Scheduler, GitHub Actions com acesso GCP, IAM, novos buckets, datasets, credenciais, transferências ou cargas reais **não** são ativados.
- O repositório é público: nunca adicionar dados reais, senhas, chaves de service account, identificadores pessoais ou arquivos licenciados.

## 2. Componentes escolhidos

| Tipo | Serviço | Regras |
| --- | --- | --- |
| Fato estruturado e histórico analítico | BigQuery | Datasets `nivon_control`, `nivon_core` e `nivon_models`; partição temporal e clustering |
| RAW autorizado e grandes volumes | Cloud Storage em `us-central1` | Bucket **privado**, objetos imutáveis por SHA e URI registrada no manifesto |
| Séries colunares | Parquet + DuckDB | Formato exportável/portátil, sem dependência exclusiva de BigQuery |
| Coletores futuros | Cloud Run | Somente após IAM, rede, budget e autorização por dataset |
| Dev/offline | SQLite | Preservar pipelines, transações, testes e recuperação local |
| Câmbio PTAX atual | Neon PostgreSQL | Manter até exportação, importação, backtest, reconciliação e retorno comprovado |

A localidade `us-central1` é um **alvo proposto** por compatibilidade e franquia elegível. Residência de dados, latência, requisitos do usuário, transferências inter-regionais e licenças devem ser validados antes do provisionamento.

## 3. Governança e esquema

Em `database/bigquery/nivon_initial_schema.sql` há um template de 4 tabelas, **não executado**:
- `control.raw_manifest`: URI do objeto, SHA-256, versão, evidência de licença, todas as datas;
- `control.ingestao_runs`: execução e falhas sanitizadas;
- `core.observacoes`: séries normalizadas, referência, publicação, coleta, competência, vintage e natureza;
- `models.previsoes`: edição do modelo, horizonte, intervalo de confiança, tendência e corte histórico.

Toda observação deve preservar fonte, dataset, referência, publicação (**NULL quando desconhecida**), coleta, competência, unidade, qualidade, tipo (OBSERVADO/INFORMADO/ESTIMADO/INFERIDO/PROJETADO/SOURCE_LAG), origem SHA e vintage. Dados sintéticos nunca podem virar dados reais. Não tratar snapshots de line-up PROGRAMADO como operação realizada.

Particionar fatos por `data_referencia`, clusterizar por dataset/indicador/região/produto e exigir filtro de partição. Não presumir UNIQUE ou chaves estrangeiras aplicadas pelo BigQuery: usar idempotência/validação no ETL. Previsões exigem timestamp de emissão e horizonte. Conectar motores por interfaces agnósticas à nuvem.

Organização de objetos (quando aprovada): `raw/{dataset_id}/{yyyy}/{mm}/{sha256}.{ext}`, `normalized/`, `features/`, `models/`, `backup/`. Os arquivos RAW ficam fora do repositório GitHub. Apenas gravar quando o direito de **armazenamento** estiver confirmado, mesmo sendo o NIVON não comercial.

## 4. Custos — política fail-closed

- Meta: **R$ 0** até autorização expressa. Nunca usar um alerta de orçamento como limite rígido de cobrança. Verificar quais serviços aceitam spend caps e as limitações.
- O **BigQuery Sandbox sem billing** não serve de arquivo durável: tabelas expiram após 60 dias, tem limite de 10 GiB de armazenamento no ciclo de vida e não aceita streaming/DML. Útil somente para demonstração descartável.
- O **Cloud Storage Always Free** concede franquia mensal de 5 GB-mês somente em `us-east1`, `us-central1` e `us-west1`, com cotas de operações e transferência; ultrapassar as cotas pode cobrar. Não criar bucket sem billing e limites revisados.
- Para BigQuery com faturamento: validar franquias vigentes, quota diária customizada para consulta, `maximum_bytes_billed` por job, dry-run, política de partição e controle de crescimento de armazenamento. Carregamento batch padrão pode ser gratuito, mas armazenamento e transferências podem ser cobrados.
- Não configurar Cloud Run min instances, conexões entre regiões, geração contínua, Scheduler ou export de logs até mensurar custo e segurança.
- Usar **Workload Identity Federation/OIDC** no GitHub quando necessário, escopo por repo/branch/ambiente e identidades de menor privilégio, sem chave JSON estática.

Fontes oficiais:
- https://docs.cloud.google.com/bigquery/docs/sandbox
- https://docs.cloud.google.com/free/docs/free-cloud-features
- https://docs.cloud.google.com/bigquery/docs/best-practices-costs
- https://docs.cloud.google.com/billing/docs/how-to/budgets
- https://docs.cloud.google.com/iam/docs/workload-identity-federation
- https://docs.cloud.google.com/bigquery/docs/loading-data-cloud-storage-parquet

## 5. Gates obrigatórios para implantação

1. Identificar projeto GCP correto e confirmar status de billing, propriedade, quotas e região. Não deduzir projeto a partir do Gmail/Drive.
2. Auditar licença, retenção, proteção de dados, acesso IAM e necessidade de bucket por dataset.
3. Aprovar controle de custo concreto antes de criar armazenamento ou jobs pagos. A configuração com `paid_use_approved:false` deve bloquear executor.
4. Preparar em ambiente isolado só arquivos sintéticos e tabelas de teste; executar validações de schema, hashes, backup, restauração e consulta as-of.
5. Exportar PTAX do Neon em backup **privado**, com contagens, datas e SHA; importar cópia, comparar por moeda/data/tipo/preço/versão e corrigir sem perda.
6. Validar no novo destino consultas equivalentes e histórico de revisões; manter Neon ativo e somente depois planejar cutover reversível sem duplicar agendas.
7. Não remover Neon nem SQLite até observar execuções consistentes em datas diferentes e completar backup/restore.
8. Reconciliar código de armazenamento das PRs #58/#61 antes de merge final; evitar duas fontes concorrentes de verdade.

## 6. Próximo passo executável

Ao obter **identificador do projeto GCP + situação de billing** em acesso autorizado, começar por inventário read-only, cotas, IAM e estimativa de custos. Em seguida teste isolado com dados sintéticos e rollback. Sem acesso a GCP, esta PR entrega apenas planejamento versionado, esquema em template e testes offline — **não comprova um sistema em nuvem**.
