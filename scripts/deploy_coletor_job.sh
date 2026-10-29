#!/usr/bin/env bash
# Deploy do Cloud Run Job nivon-coletor + Cloud Scheduler 3x/dia (07:15, 13:15, 19:15 MT).
# Pode ser executado via GitHub Actions no ambiente 'producao' ou manualmente.
# Requer recursos e IAM ja preparados pela Frente 5; NAO altera politicas IAM.
# Cada fonte so roda se estiver vencida.
# Não concede IAM amplo, não cria buckets/datasets, não torna nada público.
set -euo pipefail
P=nivon-data
R=southamerica-east1
JOB=nivon-coletor
REPO="${NIVON_COLETOR_ARTIFACT_REPO:?Informe o repositório Docker EXISTENTE (Artifact Registry)}"
SA="${NIVON_COLETOR_SA:-nivon-coletor-de-dados@nivon-data.iam.gserviceaccount.com}"
DATASET="${NIVON_BQ_DATASET:-nivon_raw}"
BUCKET="${NIVON_GCS_BUCKET:-nivon-data-raw-2026}"
CRON="${NIVON_COLETOR_CRON:-15 11,17,23 * * *}"
[[ "$(gcloud config get-value project 2>/dev/null)" == "$P" ]] || { echo "PROJETO_ATIVO_NAO_E_$P"; exit 3; }
[[ "$REPO" =~ ^[a-z][a-z0-9-]{1,62}$ ]] || { echo REPOSITORIO_INVALIDO; exit 3; }
[[ "$SA" =~ ^[a-z][a-z0-9-]{4,28}[a-z0-9]@nivon-data\.iam\.gserviceaccount\.com$ ]] || { echo SA_INVALIDA; exit 3; }
REV=$(git rev-parse --short=12 HEAD)
[[ -z "$(git status --porcelain)" ]] || { echo ARVORE_COM_ALTERACOES_LOCAIS; exit 3; }
bq show --format=none "$P:nivon_core.saude_fontes" || { echo TABELA_SAUDE_AUSENTE; exit 3; }
IMAGE="$R-docker.pkg.dev/$P/$REPO/$JOB:$REV"
gcloud builds submit . --project="$P" --region="$R" \
  --config=infra/google_cloud/cloudbuild.coletor.yaml --substitutions="_IMAGE_URI=$IMAGE"
gcloud run jobs deploy "$JOB" --project="$P" --region="$R" --image="$IMAGE" \
  --service-account="$SA" --tasks=1 --max-retries=0 --task-timeout=50m \
  --cpu=1 --memory=1Gi \
  --labels=nivon-component=coletor,managed-by=nivon-deploy \
  --set-env-vars="NIVON_COLETOR_HABILITADO=true,NIVON_BQ_PROJECT=$P,NIVON_BQ_DATASET=$DATASET,NIVON_GCS_BUCKET=$BUCKET,NIVON_REVISAO=$REV"
# F5 deve ter concedido run.invoker para a conta usada pelo Scheduler.
# Este deploy deliberadamente NAO cria/edita IAM.
URI="https://run.googleapis.com/v2/projects/$P/locations/$R/jobs/$JOB:run"
if gcloud scheduler jobs describe "$JOB-horario" --project="$P" --location="$R" >/dev/null 2>&1; then
  gcloud scheduler jobs update http "$JOB-horario" --project="$P" --location="$R" \
    --schedule="$CRON" --time-zone=UTC --uri="$URI" --http-method=POST --oauth-service-account-email="$SA"
else
  gcloud scheduler jobs create http "$JOB-horario" --project="$P" --location="$R" \
    --schedule="$CRON" --time-zone=UTC --uri="$URI" --http-method=POST --oauth-service-account-email="$SA"
fi
echo "COLETOR_IMPLANTADO revisao=$REV agenda='$CRON' UTC"
echo "Primeira execucao manual: gcloud run jobs execute $JOB --region=$R --wait"
