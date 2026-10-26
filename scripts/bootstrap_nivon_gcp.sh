#!/usr/bin/env bash
# NIVON: bootstrap executado SOMENTE no Google Cloud Shell autorizado.
# Modo padrao diagnostico. --aplicar so cria datasets/tabelas se IAM/APIs ja estiverem aprovados.
# Revisao C1: scripts/bootstrap_nivon_gcp.sh nao pode mais habilitar APIs nem alterar IAM.
# Uma condicao WIF mais forte que repo+main deve ser validada separadamente pelo administrador.

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

# Esta ferramenta NAO habilita APIs, altera IAM ou amplia WIF.
# Preparacao administrativa separada e obrigatoria, sob revisao do titular.

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
# Validacao estrita de uma condicao CEL MINIMA, sem substring enganosa.
# Expressoes mais complexas/superiores necessitam auditoria humana e ficam bloqueadas.
python3 - "$EXISTING" "$REPO" <<'PY'
import re,sys
expression, repo=sys.argv[1:]
parts=[p.strip().strip("() ").strip() for p in expression.split("&&")]
allowed={f"assertion.repository == '{repo}'",f"assertion.ref == 'refs/heads/main'"}
normalized={re.sub(r'\s*==\s*',' == ',p.replace('"',"'")) for p in parts}
if len(parts)!=2 or normalized!=allowed or '||' in expression:
    raise SystemExit('WIF_CONDICAO_NAO_HOMOLOGADA: revisar no IAM sem ampliar grants')
PY

for dataset in nivon_stage nivon_core; do
  if ! bq --project_id="$PROJECT" show --dataset "${PROJECT}:${dataset}" >/dev/null 2>&1; then
    bq --project_id="$PROJECT" --location="$REGION" mk \
        --dataset "${PROJECT}:${dataset}"
  fi
done

# Permissoes IAM e datasets sao administrados fora deste script, sob revisao humana.
# Nao adicionar WRITER, OWNER nem bindings pelo bootstrap de schema.

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
