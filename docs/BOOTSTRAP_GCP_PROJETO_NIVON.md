# NIVON — Criar projeto Google Cloud novo, do zero (21/10/2026)

Estado deste documento: **manual/bootstrap; nao executado na conta GCP**. O projeto ainda nao foi criado por esta PR. Nenhuma despesa autorizada.

## Caminho mais simples: console

1. Fazer login com a conta do proprietario em https://console.cloud.google.com/projectcreate .
2. Nome: **NIVON - Plataforma de Dados**.
3. ID sugerido: `nivon-data-2026` **somente se disponivel**. IDs sao globais e imutaveis; se ocupado escolher outra variacao e guardar o ID verdadeiro.
4. Organizacao: **Nenhuma organizacao**, se a conta permitir e nao houver uma estrutura institucional. Se aparecer organizacao obrigatoria, verificar com o titular da conta.
5. **Nao vincular faturamento.** Se o console obrigar criar/ativar Billing para a operacao seguinte, parar; nao adicionar cartao e nao ativar servicos por tentativa.
6. Criar apenas o projeto. Depois abrir https://console.cloud.google.com/home/dashboard , seleciona-lo e anotar o **ID** (nao numero, nome, e-mail nem token).
7. Abrir https://console.cloud.google.com/billing e verificar se o projeto esta **sem conta de faturamento vinculada**.
8. A regiao operacional planejada e `us-central1`; ela sera configurada **nos datasets/buckets futuros**, nao durante a criacao do projeto.

Atencao: projeto criado nao significa BigQuery operacional definitivo, storage criado, Cloud Run ativo, migracao de dados ou custo zero garantido.

## Caminho reproduzivel: Cloud Shell + script revisavel

Usar no Cloud Shell de uma conta Google Cloud autorizada:

```sh
git clone --branch plan/gcp-data-platform-20261021 \
  https://github.com/brunocapellari-dotcom/NIVON.git
cd NIVON
bash -n scripts/bootstrap_gcp_project.sh
bash scripts/bootstrap_gcp_project.sh --create nivon-data-2026
```

A criacao exige repetir o ID exato, consulta credenciais locais do CLI sem exporta-las, cria **somente o projeto vazio** e faz leitura da situacao de billing. Usa a opcao `--no-enable-cloud-apis`; **nao** faz `gcloud billing projects link`, `gcloud services enable`, `gcloud storage buckets create` ou `bq mk`.

Se o ID escolhido for outro, substituir `nivon-data-2026` no comando por ele. Nao usar `sudo`, conta de servico, chaves ou secrets do GitHub para este passo.

Para apenas conferir um projeto existente:

```sh
bash scripts/bootstrap_gcp_project.sh --check ID_REAL_DO_PROJETO
```

Se `gcloud billing projects describe` nao puder ser lido, o script falha fechado com estado indeterminado, sem presumir desativacao.

## Proximos gates apos criacao

- Obter e registrar **somente** o ID do projeto GCP; nenhuma credencial ou informacao de pagamento.
- Validar estado de Billing desativado, IAM do proprietario e se existem projetos/recursos ja vinculados por engano.
- Avaliar sandbox BigQuery usando apenas dados **descartaveis** de teste: tabelas do sandbox expiram em 60 dias, armazenamento total de vida limitado a 10 GiB e DML/streaming nao sao suportados (https://docs.cloud.google.com/bigquery/docs/sandbox).
- Para historico permanente, aceitar somente plano com custos, regiao, quotas e limites claramente acordados. O Free Tier de BigQuery (10 GiB armazenamento/mes e 1 TiB consulta/mes) com billing **nao elimina cobranca por excedentes**.
- Orçamentos Google Cloud **nao sao travas universais de gasto**. Quota BigQuery limita consultas, mas nao o custo de Cloud Storage ou outros servicos. Sem autorizacao expressa, nao vincular billing.
- Nenhum bucket/dataset/servico/agendamento ativado sem primeiro validar custo, termos de uso e direitos por operacao de cada fonte.
- Nao importar nem desligar dados PTAX no Neon ate reconciliacao de contagens, chaves, vintages, SHA, backup privado e restore.

## Estado no GitHub

- PR #84: planejamento e esquema BigQuery, **draft**, sem merge.
- PR #58: PTAX Neon atual; preservar cron e observacoes.
- PR #61: pipelines SQLite em integracao; reconciliar sem duplicar tabelas.
- Testes offline: `tests/test_gcp_plan_contract.py` e `tests/test_gcp_bootstrap.py`.

Referencias:
- https://docs.cloud.google.com/resource-manager/docs/creating-managing-projects
- https://docs.cloud.google.com/sdk/gcloud/reference/projects/create
- https://docs.cloud.google.com/sdk/gcloud/reference/billing/projects/describe
- https://docs.cloud.google.com/billing/docs/how-to/budgets
