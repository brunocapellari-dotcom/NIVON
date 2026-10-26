#!/usr/bin/env bash
# Go-live interno NIVON: serviço Cloud Run PRIVADO, somente leitura.
# Não habilita APIs, concede IAM nem agenda coletas.
set -euo pipefail
: "${NIVON_PROJETO:?}"
: "${NIVON_DATASET:?}"
: "${NIVON_TERMINAL_REPO:?}"
: "${NIVON_TERMINAL_READONLY_SA:?}"
: "${NIVON_TERMINAL_DEPLOY_APPROVED:?}"
: "${NIVON_GCP_COST_REVIEWED:?}"
test "$NIVON_PROJETO" = nivon-data || { echo PROJETO_NAO_AUTORIZADO; exit 3; }
test "$NIVON_DATASET" = nivon_raw || { echo DATASET_NAO_AUTORIZADO; exit 3; }
test "$NIVON_TERMINAL_DEPLOY_APPROVED" = true || { echo DEPLOY_NAO_AUTORIZADO; exit 3; }
test "$NIVON_GCP_COST_REVIEWED" = true || { echo CUSTO_NAO_APROVADO; exit 3; }
test "${GITHUB_REF:-}" = refs/heads/main || { echo SOMENTE_MAIN; exit 3; }
[[ "$NIVON_TERMINAL_REPO" =~ ^[a-z][a-z0-9-]{0,61}[a-z0-9]$ ]] || {
 echo REPOSITORIO_ARTIFACT_NAO_VALIDO; exit 3;
}
[[ "$NIVON_TERMINAL_READONLY_SA" =~ ^[a-z][a-z0-9-]{3,29}@nivon-data\.iam\.gserviceaccount\.com$ ]] || {
 echo CONTA_DE_SERVICO_NAO_AUTORIZADA; exit 3;
}
REGION=southamerica-east1
SERVICE=nivon-terminal
SHA="${GITHUB_SHA:-}"
[[ "$SHA" =~ ^[0-9a-f]{40}$ ]] || { echo COMMIT_NAO_VALIDADO; exit 3; }
TAG="${SHA:0:12}"
IMAGE="$REGION-docker.pkg.dev/$NIVON_PROJETO/$NIVON_TERMINAL_REPO/$SERVICE:$TAG"

# Não cria Artifact Registry nem permissões; aborta quando faltam.
gcloud artifacts repositories describe "$NIVON_TERMINAL_REPO" \
  --project="$NIVON_PROJETO" --location="$REGION" --format='value(name)' >/dev/null
gcloud iam service-accounts describe "$NIVON_TERMINAL_READONLY_SA" \
  --project="$NIVON_PROJETO" --format='value(email)' >/dev/null

python - <<'PY'
from google.cloud import bigquery
p='nivon-data';d='nivon_raw'
client=bigquery.Client(project=p,location='southamerica-east1')
ds=client.get_dataset(p+'.'+d)
if str(ds.location).lower()!='southamerica-east1':
    raise SystemExit('BIGQUERY_REGIAO_DIVERGENTE')
for view in ('vw_nivon_corredores_ferrovia_mensal',
             'vw_antt_rodovia_rgi_top16_atual'):
    x=client.get_table(p+'.'+d+'.'+view)
    if x.table_type!='VIEW':
        raise SystemExit('BIGQUERY_VIEW_DIVERGENTE:'+view)
print('PREVALIDACAO_GO_LIVE_BQ_OK')
PY

# Impede sobreposição de serviço que não foi criado/rotulado pelo NIVON.
if gcloud run services describe "$SERVICE" --project="$NIVON_PROJETO" \
     --region="$REGION" --format=json >/tmp/nivon-terminal-describe.json 2>/dev/null; then
  python - <<'PY'
import json
x=json.load(open('/tmp/nivon-terminal-describe.json'))
labels=x.get('metadata',{}).get('labels') or {}
if labels.get('nivon-component')!='terminal':
    raise SystemExit('SERVICO_EXISTENTE_NAO_PERTENCE_AO_NIVON')
PY
fi
rm -f /tmp/nivon-terminal-describe.json
echo BUILD_CONTROLADO_TERMINAL_INICIADO
gcloud builds submit . --project="$NIVON_PROJETO" \
  --config=infra/google_cloud/cloudbuild.terminal.yaml \
  --substitutions="_IMAGE_URI=$IMAGE" --quiet
echo DEPLOY_PRIVADO_INICIADO
gcloud run deploy "$SERVICE" --project="$NIVON_PROJETO" --region="$REGION" \
  --image="$IMAGE" --service-account="$NIVON_TERMINAL_READONLY_SA" \
  --no-allow-unauthenticated --ingress=all \
  --min-instances=0 --max-instances=1 --concurrency=10 \
  --cpu=1 --memory=512Mi --timeout=120 \
  --port=8080 \
  --set-env-vars=NIVON_TERMINAL_PRIVATE=true \
  --labels=nivon-component=terminal,managed-by=github-actions \
  --quiet
echo TERMINAL_PRIVADO_IMPLANTADO_NAO_PUBLICO
gcloud run services describe "$SERVICE" \
  --project="$NIVON_PROJETO" --region="$REGION" \
  --format='value(status.url)'
