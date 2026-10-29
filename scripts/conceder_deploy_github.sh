#!/usr/bin/env bash
# NIVON — Concessão ÚNICA de IAM para deploys do GitHub (terminal e coletor).
# Executar pelo proprietário no Cloud Shell, após revisão e merge.
# Não cria jobs, serviços, builds, buckets ou APIs; não configura WIF.
# Reexecutável: GRANT e add-iam-policy-binding não duplicam concessões.
set -Eeuo pipefail

falhou() {
  local codigo=$?
  printf '\nERRO: passo interrompido (linha %s, codigo %s). Nenhum erro foi ignorado.\n' "$1" "$codigo" >&2
  exit "$codigo"
}
trap 'falhou "$LINENO"' ERR

P="nivon-data"
REGIAO="southamerica-east1"
REPO="nivon"
BUCKET_BUILD="nivon-data_cloudbuild"
BUCKET_SNAPSHOT="nivon-data-raw-2026"
COLETOR="nivon-coletor-de-dados@${P}.iam.gserviceaccount.com"
TERMINAL="nivon-terminal-leitura@${P}.iam.gserviceaccount.com"
JOB="nivon-coletor"
N=0
passo() { N=$((N + 1)); printf '\n[%02d] %s\n' "$N" "$*"; }
erro() { printf '\nERRO: %s\n' "$*" >&2; exit 2; }

for comando in gcloud bq python3 grep; do
  command -v "$comando" >/dev/null || erro "Comando ausente no Cloud Shell: $comando"
done
[[ "$(gcloud config get-value project)" == "$P" ]] ||
  erro "Projeto selecionado não é $P. Rode: gcloud config set project $P"

DEPLOY="${NIVON_GCP_SERVICE_ACCOUNT:-}"
if [[ -z "$DEPLOY" ]]; then
  [[ -t 0 ]] || erro "Defina NIVON_GCP_SERVICE_ACCOUNT com o e-mail da conta vinculada ao WIF."
  printf 'Cole o valor da variável GitHub NIVON_GCP_SERVICE_ACCOUNT (e-mail completo): '
  IFS= read -r DEPLOY
fi
[[ "$DEPLOY" =~ ^[a-z][a-z0-9-]{4,28}[a-z0-9]@nivon-data\.iam\.gserviceaccount\.com$ ]] ||
  erro "E-mail da conta WIF inválido ou fora de $P: $DEPLOY"
[[ "$DEPLOY" != "$COLETOR" && "$DEPLOY" != "$TERMINAL" ]] ||
  erro "O WIF precisa usar uma conta de DEPLOY separada das de execução."

passo "Conferir conta vinculada ao WIF: $DEPLOY"
gcloud iam service-accounts describe "$DEPLOY" --project="$P" --format='value(email)'
passo "Conferir repositório e buckets existentes (sem criar recursos)"
gcloud artifacts repositories describe "$REPO" --project="$P" --location="$REGIAO" \
  --format='value(name)'
gcloud storage buckets describe "gs://$BUCKET_BUILD" --format='value(name)'
gcloud storage buckets describe "gs://$BUCKET_SNAPSHOT" --format='value(name)'

passo "Conferir coletor em produção, datasets e saude_fontes"
gcloud iam service-accounts describe "$COLETOR" --project="$P" --format='value(email)'
gcloud run jobs describe "$JOB" --project="$P" --region="$REGIAO" --format='value(name)'
for dataset in nivon_raw nivon_core; do
  bq show --project_id="$P" --format=none "$P:$dataset"
done
bq show --project_id="$P" --format=none "$P:nivon_core.saude_fontes"

passo "Bloquear IAM amplo já atribuído à conta WIF, sem revogação automática"
TMP_POLICY="$(mktemp)"
trap 'rm -f "${TMP_POLICY:-}"' EXIT
gcloud projects get-iam-policy "$P" --format=json > "$TMP_POLICY"
python3 - "$TMP_POLICY" "$DEPLOY" <<'PY'
import json, sys
policy_path, email = sys.argv[1:]
with open(policy_path, encoding="utf-8") as arquivo:
    data = json.load(arquivo)
member = f"serviceAccount:{email}"
broad = {"roles/owner", "roles/editor", "roles/run.admin",
         "roles/iam.serviceAccountAdmin", "roles/iam.serviceAccountTokenCreator",
         "roles/bigquery.admin", "roles/storage.admin"}
encontrados = sorted({entry["role"] for entry in data.get("bindings", [])
                      if member in entry.get("members", []) and entry.get("role") in broad})
if encontrados:
    raise SystemExit("BLOQUEIO: WIF já tem papel amplo (revisão humana): "
                     + ", ".join(encontrados))
print("SEM_PAPEIS_AMPLOS_DIRETOS_NO_PROJETO=OK")
PY
rm -f "$TMP_POLICY"
trap - EXIT

MEMBER="serviceAccount:$DEPLOY"
passo "Criar conta de leitura do terminal se ainda não existir"
CONTAS="$(gcloud iam service-accounts list --project="$P" --format='value(email)')"
if grep -Fxq "$TERMINAL" <<< "$CONTAS"; then
  echo "Terminal: conta já existe."
else
  gcloud iam service-accounts create nivon-terminal-leitura --project="$P" \
    --display-name="NIVON terminal leitura"
fi
gcloud iam service-accounts describe "$TERMINAL" --project="$P" --format='value(email)'

passo "Papéis de orquestração de deploy no projeto (sem Owner/Editor básicos)"
for papel in \
  roles/run.developer \
  roles/cloudbuild.builds.editor \
  roles/cloudscheduler.admin \
  roles/serviceusage.serviceUsageConsumer; do
  printf '%s => %s\n' "$DEPLOY" "$papel"
  gcloud projects add-iam-policy-binding "$P" --member="$MEMBER" \
    --role="$papel" --condition=None --format=none --quiet
done

passo "iam.serviceAccountUser SOMENTE nas contas de execução coletor e terminal"
for sa in "$COLETOR" "$TERMINAL"; do
  printf '%s => actAs em %s\n' "$DEPLOY" "$sa"
  gcloud iam service-accounts add-iam-policy-binding "$sa" --project="$P" \
    --member="$MEMBER" --role=roles/iam.serviceAccountUser \
    --format=none --quiet
done

passo "Artifact Registry Writer SOMENTE no repositório nivon"
gcloud artifacts repositories add-iam-policy-binding "$REPO" \
  --project="$P" --location="$REGIAO" --member="$MEMBER" \
  --role=roles/artifactregistry.writer --format=none --quiet

passo "Criar objetos SOMENTE no bucket de staging do Cloud Build"
gcloud storage buckets add-iam-policy-binding "gs://$BUCKET_BUILD" \
  --member="$MEMBER" --role=roles/storage.objectCreator --format=none --quiet

passo "BigQuery jobUser para execução do terminal, sem privilégio de edição"
gcloud projects add-iam-policy-binding "$P" \
  --member="serviceAccount:$TERMINAL" --role=roles/bigquery.jobUser \
  --condition=None --format=none --quiet

passo "GRANT ON SCHEMA: terminal Data Viewer em raw e core"
for dataset in nivon_raw nivon_core; do
  echo "BigQuery dataViewer: $P.$dataset"
  bq query --project_id="$P" --location="$REGIAO" --use_legacy_sql=false --quiet \
    "GRANT \`roles/bigquery.dataViewer\` ON SCHEMA \`${P}.${dataset}\` TO \"serviceAccount:${TERMINAL}\""
done

passo "WIF: leitura da tabela específica nivon_core.saude_fontes"
bq query --project_id="$P" --location="$REGIAO" --use_legacy_sql=false --quiet \
  "GRANT \`roles/bigquery.dataViewer\` ON TABLE \`${P}.nivon_core.saude_fontes\` TO \"${MEMBER}\""

passo "Terminal: metadados do bucket e GET apenas no prefixo do snapshot privado"
gcloud storage buckets add-iam-policy-binding "gs://$BUCKET_SNAPSHOT" \
  --member="serviceAccount:$TERMINAL" --role=roles/storage.bucketViewer \
  --format=none --quiet
CONDICAO="title=nivon-terminal-snapshot-v1,expression=resource.name.startsWith('projects/_/buckets/${BUCKET_SNAPSHOT}/objects/interno/nivon/portal/v1/')"
gcloud storage buckets add-iam-policy-binding "gs://$BUCKET_SNAPSHOT" \
  --member="serviceAccount:$TERMINAL" --role=roles/storage.objectViewer \
  --condition="$CONDICAO" --format=none --quiet

passo "Coletor: run.invoker SOMENTE no Cloud Run Job existente (pelo proprietário)"
gcloud run jobs add-iam-policy-binding "$JOB" --project="$P" --region="$REGIAO" \
  --member="serviceAccount:$COLETOR" --role=roles/run.invoker \
  --format=none --quiet

printf '\nIAM_CONFIGURADO_SEM_ACESSO_PUBLICO=OK\n'
printf 'WIF: %s\n' "$DEPLOY"
printf 'Coletor: %s\nTerminal: %s\n' "$COLETOR" "$TERMINAL"
echo "Nenhum serviço, build, agenda, chave ou API foi criado."
echo "IAM aplicado não comprova deploy, WIF correto, dados recentes ou proteção do GitHub."
echo "F4: o deploy via WIF não pode repetir jobs add-iam-policy-binding (run.developer não tem setIamPolicy)."
