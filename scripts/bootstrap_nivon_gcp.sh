#!/usr/bin/env bash
# NIVON: bootstrap executado SOMENTE no Google Cloud Shell autorizado.
# Modo padrao diagnostico. --aplicar provisiona recursos potencialmente faturaveis.
set -euo pipefail

PROJECT="nivon-data"
REGION="southamerica-east1"
POOL="nivon-github"
PROVIDER="github-actions"
SA_NAME="nivon-coletor-de-dados"
SA_EMAIL="${SA_NAME}@${PROJECT}.iam.gserviceaccount.com"
REPO="brunocapellari-dotcom/NIVON"
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
MAIN_WORKFLOW="${REPO}/.github/workflows/nivon-gcp-migracao.yml@refs/heads/main"
PTAX_WORKFLOW="${REPO}/.github/workflows/ptax-neon-private-export.yml@refs/heads/main"
ZARC_WORKFLOW="${REPO}/.github/workflows/nivon-gcp-zarc.yml@refs/heads/main"
PTAX_DIRECT_WORKFLOW="${REPO}/.github/workflows/ptax-bcb-direto-gcp.yml@refs/heads/main"

command -v gcloud >/dev/null || { echo 'FALTA_GCLOUD'; exit 3; }
command -v bq >/dev/null || { echo 'FALTA_BQ'; exit 3; }

# A SA e o provider sao os mesmos usados no primeiro lote real da ANTT.
# Este script so cria novos datasets/tabelas com --aplicar; nao configura WIF.
# Nada e criado enquanto o projeto/billing nao puderem ser lidos.
PROJECT_NUMBER="$(gcloud projects describe "$PROJECT" --format='value(projectNumber)')"
[[ -n "$PROJECT_NUMBER" ]] || { echo 'PROJETO_GCP_NAO_VERIFICADO'; exit 3; }
BILLING="$(gcloud billing projects describe "$PROJECT" --format='value(billingEnabled)')"
echo "NIVON_GCP_PROJECT=$PROJECT"
echo "NIVON_GCP_BILLING_ENABLED=$BILLING"
echo "NIVON_GCP_DATASET_REGION=$REGION"
if [[ "${1:-}" != "--aplicar" ]]; then
  echo 'MODO_DIAGNOSTICO: zero criacoes. Para provisionar, executar --aplicar.'
  exit 0
fi
[[ "$BILLING" == "True" || "$BILLING" == "true" ]] ||
    { echo 'FATURAMENTO_NAO_ATIVO: nao provisionado'; exit 3; }

# APIs (habilitar gera possibilidade de consumo; apenas apos --aplicar).
gcloud services enable --project "$PROJECT" \
    bigquery.googleapis.com iam.googleapis.com \
    iamcredentials.googleapis.com sts.googleapis.com

# A identidade ja foi validada por GitHub Actions com leitura GCS/BigQuery
# e carga real de ANTT 2026. Nao criar outra SA nem outro WIF no NIVON.
gcloud iam service-accounts describe "$SA_EMAIL" --project "$PROJECT" >/dev/null 2>&1 ||
  { echo 'SERVICE_ACCOUNT_EXISTENTE_AUSENTE; revisar IAM, sem criar identidade paralela'; exit 3; }
gcloud iam workload-identity-pools describe "$POOL" --location=global --project "$PROJECT" >/dev/null 2>&1 ||
  { echo 'POOL_EXISTENTE_AUSENTE; nao criar outro WIF'; exit 3; }
EXISTING="$(gcloud iam workload-identity-pools providers describe "$PROVIDER" \
  --workload-identity-pool="$POOL" --location=global --project="$PROJECT" \
  --format='value(attributeCondition)')" || {
    echo 'PROVEDOR_EXISTENTE_AUSENTE; nao criar outro WIF'; exit 3;
  }
# Nao alargar a condicao nem conceder novo Workload Identity User.
# Se a condicao atual nao garante repo+main, exigir revisao humana em IAM.
[[ "$EXISTING" == *"assertion.repository"* &&
   "$EXISTING" == *"$REPO"* &&
   "$EXISTING" == *"assertion.ref"* &&
   "$EXISTING" == *"refs/heads/main"* ]] ||
  { echo 'PROVEDOR_EXISTENTE_SEM_ESCOPO_VERIFICAVEL: revisar WIF'; exit 3; }

gcloud projects add-iam-policy-binding "$PROJECT" \
    --member="serviceAccount:$SA_EMAIL" \
    --role="roles/bigquery.jobUser" --quiet >/dev/null

for dataset in nivon_stage nivon_core; do
  if ! bq --project_id="$PROJECT" show --dataset "${PROJECT}:${dataset}" >/dev/null 2>&1; then
    bq --project_id="$PROJECT" --location="$REGION" mk \
        --dataset "${PROJECT}:${dataset}"
  fi
done

# Permissao apenas nos dois datasets do NIVON. Codigo Python usa ADC do Cloud Shell.
TMPENV="$(mktemp -d)"
trap 'rm -rf "$TMPENV"' EXIT
python3 -m venv "$TMPENV/venv"
"$TMPENV/venv/bin/pip" -q install --disable-pip-version-check google-cloud-bigquery==3.38.0
NIVON_SA_EMAIL="$SA_EMAIL" "$TMPENV/venv/bin/python" - <<'PY'
import os
from google.cloud import bigquery
project="nivon-data"
client=bigquery.Client(project=project)
sa=os.environ["NIVON_SA_EMAIL"]
for name in ("nivon_stage","nivon_core"):
    dataset=client.get_dataset(f"{project}.{name}")
    entries=list(dataset.access_entries)
    if not any(e.entity_type=="userByEmail" and e.entity_id==sa and e.role in ("WRITER","OWNER") for e in entries):
        entries.append(bigquery.AccessEntry(role="WRITER",entity_type="userByEmail",entity_id=sa))
        dataset.access_entries=entries
        client.update_dataset(dataset,["access_entries"])
print("GCP_DATASET_MINIMUM_PERMISSIONS_APPLIED")
PY

bq --project_id="$PROJECT" --location="$REGION" query \
    --use_legacy_sql=false < "$ROOT/database/bigquery/nivon_neon_legado_schema.sql"
bq --project_id="$PROJECT" --location="$REGION" query \
    --use_legacy_sql=false < "$ROOT/database/bigquery/nivon_zarc_schema.sql"

# O modelo PTAX canonico ja esta versionado no main.
sed "s/\${PROJECT_ID}/${PROJECT}/g" "$ROOT/database/bigquery/nivon_ptax_schema.sql" | \
  bq --project_id="$PROJECT" --location="$REGION" query --use_legacy_sql=false

WIF_NAME="projects/${PROJECT_NUMBER}/locations/global/workloadIdentityPools/${POOL}/providers/${PROVIDER}"
echo "NIVON_GCP_PROVIDER=$WIF_NAME"
echo "NIVON_GCP_SERVICE_ACCOUNT=$SA_EMAIL"
echo 'GCP_DATASETS_PTAX_LEGADO_ZARC_CRIADOS'
echo 'IMPORTANTE: ainda configurar no GitHub as variaveis acima e revisar limite de faturamento.'
echo 'NAO desligar nem excluir Neon ate carga e verificacao de integridade no BigQuery.'
