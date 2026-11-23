# NIVON — Bootstrap unificado de tabelas BigQuery

Data: 23/10/2026. Execução inicial da auditoria GCP: [Actions 39999587491](https://github.com/brunocapellari-dotcom/NIVON/actions/runs/39999587491).

## Recursos confirmados por leitura real
- Projeto `nivon-data`, dataset `nivon_raw`, bucket `nivon-data-raw-2026`.
- Dataset e bucket na região `southamerica-east1`.
- WIF de **leitura** GitHub → Google Cloud validado a partir da `main`.
- **Não existem** atualmente `nivon_observacoes` e `agro_publicacoes_staging`.
- Não há neste diagnóstico prova de IAM para escrita, tabela criada, execução de MERGE ou persistência ponta a ponta.

## Implementação
`src/nivon/bootstrap_tabelas_bq.py` reutiliza os contratos já existentes:
- `preflight_gcp_fontes.verificar_nuvem` para tabela **canônica** (data_referencia DATE obrigatória, partição por referência, cluster dataset/identidade/fingerprint, filtro obrigatório de partição).
- `agro_staging_bigquery.verificar_ou_criar_tabela` para tabela **não canônica** (data_referencia anulável, partição por data_coleta). Publicações IMEA/CONAB sem data de referência confiável continuam em quarentena, não no canônico.
- `auditoria_gcp_readonly.auditar` antes e depois: schema/partição existentes não são modificados. Leitura posterior independente confirma o resultado.
- Não cria projeto, dataset, bucket, serviços Cloud ou usuários. Não ingere dados e não executa consulta analítica.

### GitHub Actions — controle único sem Cloud Shell
Após merge na `main`, abrir:
[Actions — NIVON - Preparar tabelas Google Cloud](https://github.com/brunocapellari-dotcom/NIVON/actions/workflows/bootstrap-tabelas-gcp.yml)

Escolher `Run workflow`, branch `main`, destino `ambas`. Com `aplicar=false` a execução só informa quais faltam. Com `aplicar=true` cria **somente tabelas ausentes**, mantendo os mesmos schemas dos pipelines. O ambiente de GitHub `nivon-gcp-producao` e o provedor WIF restringem quem pode executar.

### Variáveis de GitHub Actions
Existência/identidade: `NIVON_GCP_PROVIDER`, `NIVON_GCP_SERVICE_ACCOUNT`, `NIVON_BQ_PROJECT`, `NIVON_BQ_DATASET`, `NIVON_GCS_BUCKET`.

Quando `aplicar=true`, exigir previamente:
- `NIVON_ZERO_COST_BQ_APPROVED=true` (aprovação de limite e monitoramento financeiro; **não garante custo zero**).
- `NIVON_BQ_BOOTSTRAP_TABLE_APPROVED=true` para `nivon_observacoes`.
- `NIVON_AGRO_STAGING_SCHEMA_APPROVED=true` e `NIVON_AGRO_GCP_WRITE_APPROVED=true` para `agro_publicacoes_staging`.

Em `ambas`, os quatro gates devem estar ativos **antes** da primeira criação. Em alvos individuais só os respectivos gates são exigidos. Não definir flags automaticamente, nem ampliar IAM para contornar erro. São necessárias permissões efetivas de criação de tabela no dataset existente, aprovadas pelo operador.

## Invariantes e limites
- O pipeline de coletor e carga continua **desativado** até a autorização de persistência, acesso a dados e custos.
- A criação de duas tabelas não é uma transação única do BigQuery; em falha parcial, repetir o workflow é idempotente e só completa a tabela ausente.
- Tabelas existentes com esquema/partição divergentes bloqueiam bootstrap sem alterar ou apagar conteúdo.
- Não existe reversão destrutiva automática nem remoção de tabela de terceiros.
- Depois do bootstrap, validar a auditoria read-only e executar coleta+GCS+MERGE+readback com dados reais em lote pequeno sob aprovação. Não promover CEPEA/IMEA/CONAB de quarentena sem datas e direitos conferidos.

## Estado
**Código de bootstrap foi adicionado ao GitHub; a execução real de escrita permanece pendente dos gates de aprovação e IAM.** A auditoria de leitura anterior apenas confirmou a infraestrutura base.
