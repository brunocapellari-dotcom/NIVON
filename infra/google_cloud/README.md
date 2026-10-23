# NIVON marítimo — implantação no Google Cloud

## Arquitetura canônica

Google Cloud é a infraestrutura operacional: Cloud Run Jobs para coleta,
Cloud Storage para histórico de evidências imutáveis por SHA-256, BigQuery
como fonte analítica única, Cloud Scheduler para execuções agendadas.

O GitHub Actions executa apenas QA/inspeções públicas read-only.
A persistência Neon foi desativada do workflow; tabelas antigas não são
apagadas. Implementação em PR não equivale a implantação no Google Cloud.

## Recursos já implementados no código

- src/nivon/maritimo_lote.py: lote de coletores HTML com quarentena CDP.
- src/nivon/maritimo_cloud_storage.py: evidências por hash no bucket GCS.
- src/nivon/maritimo_bigquery.py: estágio SQLite local e MERGE BigQuery.
- src/nivon/maritimo_gcp_job.py: entrada para Cloud Run Job, usa ADC.
- infra/google_cloud/maritimo_bigquery.sql: DDL versionado, particionamento,
  clusterização e visão de frescor das fontes.
- infra/google_cloud/Dockerfile.maritimo e cloudbuild.maritimo.yaml: imagem.

## Pré-requisitos para executar no Google Cloud real

1. Descobrir qual PROJECT_ID, REGION, bucket e repositório Artifact Registry
   o NIVON já utiliza. Evitar duplicação de projetos/recursos.
2. Confirmar billing, quotas, permissões e localização do BigQuery antes de
   criar dataset nivon_maritimo. Aplique o DDL (substituindo placeholders
   exatos) com um papel administrativo uma única vez.
3. Identidade de Cloud Run dedicada: roles/bigquery.jobUser no projeto,
   roles/bigquery.dataEditor somente no dataset, permissão para criar e
   ler metadados de objetos GCS no bucket selecionado; não usar chaves JSON.
4. Cloud Scheduler com identidade independente autorizada para run.jobs.run
   no job específico, autenticação OAuth para a API Cloud Run Jobs.
5. Validar fontes e direitos operacionais. Santarém/Vila do Conde sempre em
   quarentena até reconciliação; Amaggi não é embarque confirmado via AIS.
6. Ativar NIVON_MARITIMO_COLETA_HABILITADA=true somente após os testes
   E2E reais de GCS -> BQ e observabilidade/contagem/custos.

## Exemplo: build e job (NÃO executado nesta sessão)

Substituir as variáveis pelas configurações reais já existentes:

    PROJECT_ID='projeto-real'
    REGION='southamerica-east1'
    DATASET_ID='nivon_maritimo'
    BUCKET='bucket-privado-existente'
    REPO='artifact-registry-existente'
    JOB_SA='service-account-job'
    SCHEDULER_SA='service-account-scheduler'
    IMAGE="$REGION-docker.pkg.dev/$PROJECT_ID/$REPO/nivon-maritimo:20261023"

    gcloud builds submit --project="$PROJECT_ID" \
      --config=infra/google_cloud/cloudbuild.maritimo.yaml \
      --substitutions="_IMAGE_URI=$IMAGE" .

    gcloud run jobs deploy nivon-maritimo \
      --project="$PROJECT_ID" --region="$REGION" --image="$IMAGE" \
      --service-account="$JOB_SA" --tasks=1 --parallelism=1 \
      --max-retries=0 --task-timeout=900s --memory=1Gi --cpu=1 \
      --set-env-vars="GOOGLE_CLOUD_PROJECT=$PROJECT_ID,NIVON_MARITIMO_DATASET=$DATASET_ID,NIVON_MARITIMO_BUCKET=$BUCKET,NIVON_MARITIMO_COLETA_HABILITADA=false,NIVON_PORTWATCH_COLETA_HABILITADA=false"

Aplicar o DDL com projeto e dataset confirmados antes do primeiro job.
O container não cria dataset e não ativa coleta automaticamente.

Depois de inspeção e autorização operacional, o Cloud Scheduler pode usar
HTTP POST para a API run.googleapis.com/v2/projects/PROJECT/locations/REGION/
jobs/nivon-maritimo:run, autenticada por OAuth do Scheduler (escopo cloud-platform),
no cron 12 */6 * * * (UTC). Configurar na região do projeto e confirmar custos.
Não agendar também pelo GitHub Actions.

## Limitações e validação

- Testes de GCS/BQ em CI são simulados, não comprovam credenciais ou deploy.
- Imbituba e PortWatch foram lidos em testes read-only na rodada anterior.
- Captura HTML GCS hoje é o HTML decodificado e reencodado UTF-8, não a
  sequência literal de bytes do HTTP upstream.
- MERGE por chaves naturais impede duplicata de registros; erros parciais
  entre tabelas podem ser recuperados por replay das evidências GCS.
- Partição de escalas por data_referencia (nula quando fonte não fornece);
  nunca substituir implicitamente pelo timestamp de coleta.
- AIS Amaggi necessita geocerca validada e cobertura real; não inventar carga.
- São necessárias checagens de limites BigQuery, custos, retenção GCS,
  monitoramento, freshness, IAM, rollback e reconciliador de revisões.
- No código, o modo GCP exige explicitamente bucket/dataset/projeto,
  variáveis e service account via ADC; não há segredo Neon em uso.

## Portas de entrada reais pendentes

Nao há plugin GCP com escrita habilitada nesta conversa. Para go-live,
um operador autenticado precisa configurar esses recursos na conta Google
Cloud verdadeira; não pedir senha, chave de service account ou credencial
privilegiada em mensagens. Sem isso, não afirmar coleta em produção.
