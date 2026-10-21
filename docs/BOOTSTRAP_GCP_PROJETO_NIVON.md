# NIVON — projeto `nivon-data` criado: auditoria inicial (21/10/2026)

**Evidência:** captura do Console Google Cloud enviada pelo usuário mostra projeto **NIVON**, ID **`nivon-data`**, e nome de organização exibido **`brunocapellari-org`**. O ID numérico da organização, a vinculação de faturamento, os papéis IAM e os serviços efetivamente provisionados **ainda não foram confirmados por API**.

**Atenção:** este documento e a PR #84 não criaram recursos no GCP nem habilitaram cobrança. O projeto foi criado externamente pelo usuário. **Não criar outro projeto.** Descartar o ID sugerido anteriormente `nivon-data-2026`.

## 1. Verificação simples pelo celular

1. Abra https://console.cloud.google.com/home/dashboard?project=nivon-data e selecione **NIVON** com ID `nivon-data` no seletor superior.
2. Abra https://console.cloud.google.com/billing?project=nivon-data (ou Menu ☰ → **Faturamento**).
3. Verifique se o projeto está **sem conta de faturamento vinculada**, **com conta vinculada** ou se o console informa **falta de permissão**. Caso não seja possível verificar, a situação continua **INDETERMINADA**.
4. **Não cadastrar cartão, não vincular faturamento e não ativar APIs** para concluir esta etapa.
5. Após verificar billing, inventariar APIs em https://console.cloud.google.com/apis/dashboard?project=nivon-data e permissões em https://console.cloud.google.com/iam-admin/iam?project=nivon-data; apenas leitura.
6. Informar somente o estado de faturamento, por texto ou captura sem dados de pagamento. Nunca compartilhar chaves, senhas ou tokens.

## 2. Cloud Shell / CLI — verificação somente leitura

O script existente `scripts/bootstrap_gcp_project.sh` também aceita `--create`, mas **não usar esse modo no projeto existente**. Executar apenas:

```sh
git clone --branch plan/gcp-data-platform-20261021 \
  https://github.com/brunocapellari-dotcom/NIVON.git
cd NIVON
bash -n scripts/bootstrap_gcp_project.sh
bash scripts/bootstrap_gcp_project.sh --check nivon-data
```

O modo `--check` lê projeto e situação de billing via `gcloud`, sem criar projeto, API, banco, bucket ou rotina. Se não tiver permissão para verificar billing, falha bloqueada; **falta de permissão não significa ausência de cobrança**.

Consultas adicionais apenas de leitura:

```sh
gcloud projects describe nivon-data --format='yaml(projectId,name,parent)'
gcloud billing projects describe nivon-data --format='json'
gcloud services list --enabled --project=nivon-data --format='value(config.name)'
```

## 3. Próximos gates da plataforma

- Configuração canônica em `config/gcp_data_platform.v1.json`: ID identificado por captura, sem comprovação por API, status de faturamento desconhecido e serviços desativados.
- Região planejada para datasets/buckets futuros: `us-central1`, sujeita à auditoria de licença, região e custo. Projetos GCP não recebem essa região na criação.
- Sandbox BigQuery sem billing é **descartável**, com expiração de tabelas (60 dias) e limites próprios; não é arquivo histórico durável. https://docs.cloud.google.com/bigquery/docs/sandbox
- A franquia gratuita com billing não é trava de gastos. Orçamentos são alertas, não hard cap universal. https://docs.cloud.google.com/billing/docs/how-to/budgets
- Não implantar BigQuery definitivo, Cloud Storage ou Cloud Run antes de confirmar faturamento, IAM, direitos sobre datasets, orçamento e limites técnicos de consumo.
- Preservar PTAX no Neon (PR #58) e código SQLite (PR #61) até backup/restauração, reconciliação de contagens, vintages, datas e corte reversível.

**Estado:** imagem confirma identificação do projeto, mas não prova ambiente provisionado nem billing desligado. A PR #84 continua rascunho, sem merge e sem implantação real.
