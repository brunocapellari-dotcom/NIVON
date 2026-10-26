#!/usr/bin/env bash
# Deploy privado do NIVON Terminal. Exige aprovação: não habilita APIs,
# não cria Artifact Registry, IAM, SA, Scheduler nem domínio.
set -euo pipefail

if [[ "${GITHUB_REF:-}" != "refs/heads/main" ]]; then
  echo 'BLOQUEADO_DEPLOY_SOMENTE_MAIN'
  exit 3
fi
if [[ "${NIVON_GO_LIVE_DEPLOY_APPROVED:-}" != true ||
      "${NIVON_GCP_COST_REVIEWED:-}" != true ]]; then
  echo 'BLOQUEADO_SEM_APROVACAO_DEPLOY_E_CUSTOS'
  exit 3
fi
: "${NIVON_TERMINAL_ARTIFACT_REPO:?Informe repositório Docker EXISTENTE}"
: "${NIVON_TERMINAL_EXECUTION_SA:?Informe service account EXISTENTE somente leitura}"
test "${NIVON_PROJETO:-}" = "nivon-data" || { echo 'PROJETO_DIVERGENTE'; exit 3; }
test "${NIVON_DATASET:-}" = "nivon_raw" || { echo 'DATASET_DIVERGENTE'; exit 3; }
REGION=southamerica-east1
SERVICE=nivon-terminal
[[ "$NIVON_TERMINAL_ARTIFACT_REPO" =~ ^[a-z][a-z0-9-]{1,62}$ ]] ||
  { echo 'REPOSITORY_INVALIDO'; exit 3; }
[[ "$NIVON_TERMINAL_EXECUTION_SA" =~ ^[a-z][a-z0-9-]{4,28}[a-z0-9]@nivon-data\.iam\.gserviceaccount\.com$ ]] ||
  { echo 'SA_INVALIDA_OU_EXTERNA'; exit 3; }
[[ "${GITHUB_SHA:-}" =~ ^[0-9a-f]{40}$ ]] || { echo 'SHA_COMMIT_INVALIDO'; exit 3; }

gcloud artifacts repositories describe "$NIVON_TERMINAL_ARTIFACT_REPO" \
  --project="$NIVON_PROJETO" --location="$REGION" --format=json >/dev/null
gcloud iam service-accounts describe "$NIVON_TERMINAL_EXECUTION_SA" \
  --project="$NIVON_PROJETO" --format='value(email)' >/dev/null

python - <<'PY'
from google.cloud import bigquery
import os
p=os.environ['NIVON_PROJETO'];d=os.environ['NIVON_DATASET']
c=bigquery.Client(project=p,location='southamerica-east1')
data=c.get_dataset(p+'.'+d)
if str(data.location).lower()!='southamerica-east1':
    raise SystemExit('REGIAO_BQ_DIVERGENTE')
view=c.get_table(p+'.'+d+'.vw_antt_ferrovia_od_atual')
if view.table_type!='VIEW':
    raise SystemExit('VIEW_FERROVIA_NAO_HABILITADA')
print('VIEW_E_DATASET_VALIDOS_SEM_CONSULTA_BQ')
PY

tmp=$(mktemp)
trap 'rm -f "$tmp"' EXIT
gcloud run services list --project="$NIVON_PROJETO" --region="$REGION" \
    --format=json > "$tmp"
FOUND=$(python - "$tmp" <<'PY'
import json,sys
s=json.load(open(sys.argv[1]))
for item in s:
    metadata=item.get('metadata',{})
    name=metadata.get('name','')
    if name=='nivon-terminal' or item.get('name','').endswith('/nivon-terminal'):
        labels=metadata.get('labels') or item.get('labels') or {}
        if labels.get('nivon-component')!='terminal':
            raise SystemExit('SERVICO_EXISTENTE_SEM_LABEL_NIVON')
        print('true')
        break
else: print('false')
PY
)
if [[ "$FOUND" == true ]]; then
  gcloud run services get-iam-policy "$SERVICE" --project="$NIVON_PROJETO" \
      --region="$REGION" --format=json > "$tmp"
  python - "$tmp" <<'PY'
import json,sys
policy=json.load(open(sys.argv[1]))
for item in policy.get('bindings',[]):
    if item.get('role')=='roles/run.invoker' and (
        'allUsers' in item.get('members',[]) or
        'allAuthenticatedUsers' in item.get('members',[])
    ):
        raise SystemExit('SERVICO_ATUAL_COM_INVOKER_PUBLICO_NAO_ATUALIZAR')
PY
fi

TAG="${GITHUB_SHA:0:12}"
IMAGE="$REGION-docker.pkg.dev/$NIVON_PROJETO/$NIVON_TERMINAL_ARTIFACT_REPO/nivon-terminal:$TAG"
echo 'INICIANDO_BUILD_APROVADO'
gcloud builds submit . --project="$NIVON_PROJETO" \
    --config=infra/google_cloud/cloudbuild.terminal.yaml \
    --substitutions="_IMAGE_URI=$IMAGE" --quiet

echo 'DEPLOY_PRIVADO_MIN_INSTANCES_ZERO'
gcloud run deploy "$SERVICE" \
  --project="$NIVON_PROJETO" --region="$REGION" \
  --image="$IMAGE" --service-account="$NIVON_TERMINAL_EXECUTION_SA" \
  --no-allow-unauthenticated --ingress=all \
  --min-instances=0 --max-instances=1 \
  --cpu=1 --memory=512Mi --concurrency=8 --timeout=60 \
  --labels=nivon-component=terminal,managed-by=github-actions \
  --set-env-vars="NIVON_BQ_PROJECT=$NIVON_PROJETO,NIVON_BQ_DATASET=$NIVON_DATASET" \
  --quiet
echo 'DEPLOY_TERMINAL_CONCLUIDO_PRIVADO_SEM_CRON_OU_IAM_PUBLICO'
gcloud run services describe "$SERVICE" --project="$NIVON_PROJETO" \
  --region="$REGION" --format='value(status.url)'
