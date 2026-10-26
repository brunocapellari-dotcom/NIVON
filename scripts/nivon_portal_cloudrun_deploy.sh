#!/usr/bin/env bash
# Somente manual: deploy do portal privado; sem alterar IAM publico ou habilitar APIs.
set -euo pipefail
test "${GITHUB_REF:-}" = "refs/heads/main" || { echo "PORTAL_SOMENTE_MAIN"; exit 3; }
for value in "${NIVON_GCP_COST_REVIEWED:-}" "${NIVON_PORTAL_DEPLOY_APPROVED:-}" \
             "${NIVON_PORTAL_GCS_READ_APPROVED:-}" "${NIVON_PORTAL_PRIVATE_BUCKET_REVIEWED:-}"; do
  test "$value" = true || { echo 'PORTAL_GATE_NAO_APROVADO'; exit 3; }
done
test "${NIVON_BQ_PROJECT:-}" = "nivon-data" || { echo 'PROJETO_DIVERGENTE'; exit 3; }
test "${NIVON_GCS_BUCKET:-}" = "nivon-data-raw-2026" || { echo 'BUCKET_DIVERGENTE'; exit 3; }
test "${NIVON_GCP_REGION:-southamerica-east1}" = "southamerica-east1" || exit 3
[[ "${NIVON_PORTAL_SERVICE_ACCOUNT:-}" =~ ^[a-z][a-z0-9-]{2,28}@nivon-data\.iam\.gserviceaccount\.com$ ]] || { echo 'SA_INVALIDA'; exit 3; }
[[ "${NIVON_PORTAL_ARTIFACT_REPO:-}" =~ ^[a-z][a-z0-9-]{0,61}[a-z0-9]$ ]] || { echo 'ARTIFACT_REPO_INVALIDO'; exit 3; }
[[ "${GITHUB_SHA:-}" =~ ^[0-9a-f]{40}$ ]] || { echo 'COMMIT_SHA_INVALIDO'; exit 3; }
: "${RUNNER_TEMP:?Execucao restrita ao runner autorizado}"
PROJECT=nivon-data
REGION=southamerica-east1
SERVICE=nivon-portal-interno
REPO="$NIVON_PORTAL_ARTIFACT_REPO"
TAG="$(printf '%s' "$GITHUB_SHA" | cut -c1-12)"
IMAGE="$REGION-docker.pkg.dev/$PROJECT/$REPO/nivon-portal:$TAG"

# Reutilizar Artifact Registry existente, sem provisionamento oculto.
gcloud artifacts repositories describe "$REPO" --project="$PROJECT" \
  --location="$REGION" --format='value(name)' > /dev/null

if gcloud run services describe "$SERVICE" --project="$PROJECT" --region="$REGION" \
  --format=json >"$RUNNER_TEMP/portal-before.json" 2>"$RUNNER_TEMP/portal-exists.err"; then
  python3 - "$RUNNER_TEMP/portal-before.json" <<'PY'
import json,sys
d=json.load(open(sys.argv[1]))
labels=(d.get("metadata") or {}).get("labels") or d.get("labels") or {}
if labels.get("nivon-component")!="portal-interno":
    raise SystemExit("SERVICO_PREEXISTENTE_FORA_DO_NIVON")
PY
  gcloud run services get-iam-policy "$SERVICE" --project="$PROJECT" \
    --region="$REGION" --format=json >"$RUNNER_TEMP/portal-iam-before.json"
  python3 - "$RUNNER_TEMP/portal-iam-before.json" <<'PY'
import json,sys
d=json.load(open(sys.argv[1]))
for b in d.get("bindings",[]):
    if set(b.get("members",[])) & {"allUsers","allAuthenticatedUsers"}:
        raise SystemExit("PORTAL_PREEXISTENTE_IAM_PUBLICO")
PY
else
  if ! grep -Eiq 'NOT_FOUND|not found|does not exist|404' "$RUNNER_TEMP/portal-exists.err"; then
    echo "SERVICO_PORTAL_INDETERMINADO"; exit 3
  fi
fi

# Cloud Build pode gerar cobranca: exige gate economico acima.
gcloud builds submit . --project="$PROJECT" \
  --config=infra/google_cloud/cloudbuild.portal.yaml \
  --substitutions="_IMAGE_URI=$IMAGE" --quiet

gcloud run deploy "$SERVICE" --project="$PROJECT" --region="$REGION" \
  --image="$IMAGE" --platform=managed \
  --service-account="$NIVON_PORTAL_SERVICE_ACCOUNT" \
  --no-allow-unauthenticated --ingress=all \
  --min-instances=0 --max-instances=1 --cpu=1 --memory=512Mi \
  --concurrency=20 --timeout=45s --port=8080 \
  --labels=nivon-component=portal-interno,managed-by=github-actions \
  --set-env-vars="GOOGLE_CLOUD_PROJECT=$PROJECT,NIVON_PORTAL_GCS_BUCKET=$NIVON_GCS_BUCKET,NIVON_PORTAL_PRIVATE_INGRESS_APPROVED=true,NIVON_PORTAL_GCS_READ_APPROVED=true,NIVON_PORTAL_PRIVATE_BUCKET_REVIEWED=true" \
  --quiet

# Confere IAM depois, sem mutar politicas de acesso.
gcloud run services get-iam-policy "$SERVICE" --project="$PROJECT" \
  --region="$REGION" --format=json >"$RUNNER_TEMP/portal-iam-after.json"
python3 - "$RUNNER_TEMP/portal-iam-after.json" <<'PY'
import json,sys
d=json.load(open(sys.argv[1]))
for b in d.get("bindings",[]):
    if set(b.get("members",[])) & {"allUsers","allAuthenticatedUsers"}:
        raise SystemExit("PORTAL_IAM_PUBLICO_APOS_DEPLOY")
print("PORTAL_CLOUD_RUN_IAM_PRIVADO_VERIFICADO")
PY
echo 'PORTAL_DEPLOY_PRIVADO_SEM_SCHEDULER'
