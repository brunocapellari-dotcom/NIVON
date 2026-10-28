#!/usr/bin/env bash
# Preparação ÚNICA do projeto nivon-data para o Cloud Run Job nivon-coletor.
# Executar pelo DONO no Cloud Shell, na raiz do clone, ANTES do deploy.
# Idempotente: consulta antes de criar e para no primeiro erro.
# Nunca concede papéis amplos (Owner/Editor) nem acesso público.
set -euo pipefail
P=nivon-data
R=southamerica-east1
REPO=nivon
SA_NOME=nivon-coletor-de-dados
SA="$SA_NOME@$P.iam.gserviceaccount.com"
BUCKET=nivon-data-raw-2026
# Datasets que as 4 fontes gravam (lidos dos pipelines):
#   nivon_core: ptax_quotes + staging temporário do PTAX + saude_fontes
#   nivon_raw:  ANTT ferroviário, CONAB (staging agro) e marítimo
DATASETS=(nivon_core nivon_raw)
passo() { printf '\n==> %s\n' "$*"; }

[[ "$(gcloud config get-value project 2>/dev/null)" == "$P" ]] || {
  echo "Projeto ativo não é $P. Rode: gcloud config set project $P"; exit 3; }
[[ -f database/bigquery/nivon_saude_fontes.sql ]] || { echo "Rode na raiz do clone do NIVON"; exit 3; }
PN=$(gcloud projects describe "$P" --format='value(projectNumber)')
BUILD_SA="$PN-compute@developer.gserviceaccount.com"  # conta padrão do Cloud Build

passo "1/6 Ativando APIs: Cloud Run, Cloud Build, Artifact Registry, Cloud Scheduler, BigQuery"
gcloud services enable run.googleapis.com cloudbuild.googleapis.com \
  artifactregistry.googleapis.com cloudscheduler.googleapis.com bigquery.googleapis.com --project="$P"

passo "2/6 Repositório Docker '$REPO' em $R (mantém só as 3 últimas imagens)"
if gcloud artifacts repositories describe "$REPO" --project="$P" --location="$R" >/dev/null 2>&1; then
  echo "Já existe."
else
  gcloud artifacts repositories create "$REPO" --project="$P" --location="$R" \
    --repository-format=docker --description="Imagens NIVON (coletor e terminal)"
fi
POLITICA=$(mktemp)
trap 'rm -f "$POLITICA"' EXIT
cat > "$POLITICA" <<'JSON'
[{"name": "manter-3-ultimas", "action": {"type": "Keep"}, "mostRecentVersions": {"keepCount": 3}},
 {"name": "apagar-demais", "action": {"type": "Delete"}, "condition": {"tagState": "any"}}]
JSON
gcloud artifacts repositories set-cleanup-policies "$REPO" --project="$P" --location="$R" \
  --policy="$POLITICA" --no-dry-run

passo "3/6 Conta de serviço $SA"
if gcloud iam service-accounts describe "$SA" --project="$P" >/dev/null 2>&1; then
  echo "Já existe."
else
  gcloud iam service-accounts create "$SA_NOME" --project="$P" --display-name="NIVON coletor de dados"
fi

passo "4/6 Permissões mínimas da conta do coletor"
echo "- bigquery.jobUser no projeto (executar consultas e cargas)"
gcloud projects add-iam-policy-binding "$P" --member="serviceAccount:$SA" \
  --role=roles/bigquery.jobUser --condition=None --format=none
# Datasets ausentes são criados na mesma localização do nivon_raw (onde já estão os dados).
LOCAL_BQ=$(bq show --format=json "$P:nivon_raw" | python3 -c 'import json,sys; print(json.load(sys.stdin)["location"])')
[[ -n "$LOCAL_BQ" ]] || { echo "Localização do nivon_raw não encontrada"; exit 3; }
echo "- localização BigQuery (lida do nivon_raw): $LOCAL_BQ"
for ds in "${DATASETS[@]}"; do
  if bq show --format=none "$P:$ds" >/dev/null 2>&1; then
    echo "- dataset $ds já existe"
  else
    echo "- criando dataset $ds em $LOCAL_BQ"
    bq mk --dataset --location="$LOCAL_BQ" --description="NIVON $ds" "$P:$ds"
  fi
  echo "- bigquery.dataEditor só no dataset $ds (GRANT ON SCHEMA)"
  bq query --project_id="$P" --location="$LOCAL_BQ" --use_legacy_sql=false --quiet \
    "GRANT \`roles/bigquery.dataEditor\` ON SCHEMA \`$P.$ds\` TO \"serviceAccount:$SA\""
done
echo "- storage.objectAdmin só no bucket gs://$BUCKET (bruto com hash e readback)"
gcloud storage buckets add-iam-policy-binding "gs://$BUCKET" --member="serviceAccount:$SA" \
  --role=roles/storage.objectAdmin --format=none

passo "5/6 Conta do Cloud Build ($BUILD_SA): publicar imagem e gravar logs do build"
gcloud artifacts repositories add-iam-policy-binding "$REPO" --project="$P" --location="$R" \
  --member="serviceAccount:$BUILD_SA" --role=roles/artifactregistry.writer --format=none
gcloud projects add-iam-policy-binding "$P" --member="serviceAccount:$BUILD_SA" \
  --role=roles/logging.logWriter --condition=None --format=none
FONTE_BUILD="gs://${P}_cloudbuild"
gcloud storage buckets describe "$FONTE_BUILD" --format=none >/dev/null 2>&1 ||
  gcloud storage buckets create "$FONTE_BUILD" --project="$P" --location="$R" --uniform-bucket-level-access
gcloud storage buckets add-iam-policy-binding "$FONTE_BUILD" --member="serviceAccount:$BUILD_SA" \
  --role=roles/storage.objectViewer --format=none

passo "6/6 Tabelas que o coletor grava (CREATE TABLE IF NOT EXISTS, nada é recriado)"
criar_tabela() {  # $1 = SQL versionado, $2 = tabela esperada, $3 = dataset do placeholder
  echo "- $2"
  sed -e "s/\${PROJECT_ID}/$P/g" -e "s/\${DATASET_ID}/$3/g" "$1" |
    bq query --project_id="$P" --location="$LOCAL_BQ" --use_legacy_sql=false --quiet
  bq show --format=none "$P:$2"
}
criar_tabela database/bigquery/nivon_saude_fontes.sql nivon_core.saude_fontes nivon_core
criar_tabela database/bigquery/nivon_ptax_schema.sql nivon_core.ptax_quotes nivon_core
criar_tabela sql/bigquery/002_agro_fontes_staging.sql nivon_raw.agro_fonte_stage nivon_raw

printf '\nPREPARACAO_CONCLUIDA. Próximo passo, no mesmo terminal:\n\n'
echo "  NIVON_COLETOR_ARTIFACT_REPO=$REPO NIVON_COLETOR_SA=$SA bash scripts/deploy_coletor_job.sh"
echo "  gcloud run jobs execute nivon-coletor --region=$R --wait"
