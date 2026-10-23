#!/usr/bin/env bash
# Deploy controlado, sem habilitar API, conceder IAM ou criar Scheduler.
set -euo pipefail
: "${NIVON_PROJETO:?Informe NIVON_PROJETO}"
: "${NIVON_DATASET:?Informe NIVON_DATASET}"
: "${NIVON_BUCKET:?Informe NIVON_BUCKET}"
: "${NIVON_EXECUTION_SA:?Informe NIVON_EXECUTION_SA}"
test "$NIVON_PROJETO" = "nivon-data" || { echo 'PROJETO_DIVERGENTE'; exit 3; }
test "$NIVON_DATASET" = "nivon_raw" || { echo 'DATASET_DIVERGENTE'; exit 3; }
test "$NIVON_BUCKET" = "nivon-data-raw-2026" || { echo 'BUCKET_DIVERGENTE'; exit 3; }
test "$NIVON_EXECUTION_SA" = "nivon-coletor-de-dados@nivon-data.iam.gserviceaccount.com" || { echo 'SA_NAO_HOMOLOGADA'; exit 3; }
test "${NIVON_GCP_REGION:-southamerica-east1}" = "southamerica-east1" || { echo 'REGIAO_DIVERGENTE'; exit 3; }
if [ "${GITHUB_REF:-refs/heads/main}" != "refs/heads/main" ]; then
 echo 'DEPLOY_SOMENTE_MAIN'
 exit 3
fi
REGION=southamerica-east1
# IAM de ingestao nao precisa ter serviceusage.services.get.
# A validacao ocorre pelas operacoes alvo: listar repo Docker, fazer build
# e deploy; cada falha retorna codigo especifico, sem ampliar IAM.
# Reutilizar repositório Docker existente; nunca criar repositório por surpresa.
REPO="${NIVON_MARITIMO_ARTIFACT_REPO:-}"
if [ -z "$REPO" ]; then
  REPO="$(gcloud artifacts repositories list --project="$NIVON_PROJETO" --location="$REGION" --format=json | python3 -c '
import sys,json
found=[x.get("name","").rsplit("/",1)[-1] for x in json.load(sys.stdin)
       if x.get("format")=="DOCKER"]
if len(found)!=1:
    raise SystemExit("ESPECIFICAR_NIVON_MARITIMO_ARTIFACT_REPO_OU_CRIAR_REPO_AUTORIZADO")
print(found[0])')"
fi
[[ "$REPO" =~ ^[a-z][a-z0-9-]{0,61}[a-z0-9]$ ]] || { echo 'REPO_INVALIDO'; exit 3; }
gcloud artifacts repositories describe "$REPO" --project="$NIVON_PROJETO" --location="$REGION" --format='value(name)' >/dev/null
TAG="${GITHUB_SHA:-local}"
[[ "$TAG" =~ ^[0-9a-f]{12,40}$ ]] || { echo 'TAG_DO_COMMIT_INVALIDA'; exit 3; }
TAG="${TAG:0:12}"
IMAGE="$REGION-docker.pkg.dev/$NIVON_PROJETO/$REPO/nivon-maritimo:$TAG"
# Verificar que dados RAW e tabelas existem: não criar outros bancos.
python3 - <<'PY'
import os
from google.cloud import bigquery, storage
p=os.environ['NIVON_PROJETO'];d=os.environ['NIVON_DATASET'];b=os.environ['NIVON_BUCKET']
client=bigquery.Client(project=p,location='southamerica-east1')
ds=client.get_dataset(p+'.'+d)
bucket=storage.Client(project=p).get_bucket(b)
if str(ds.location).lower()!='southamerica-east1' or str(bucket.location).lower()!='southamerica-east1':
 raise SystemExit('REGIAO_STORAGE_BIGQUERY_DIVERGENTE')
for table in ('maritimo_capturas','maritimo_escalas_revisoes',
              'maritimo_fluxos_passagens','maritimo_coleta_execucoes'):
 client.get_table(p+'.'+d+'.'+table)
print('BIGQUERY_E_GCS_EXISTENTES_VALIDADO')
PY
# Não sobrescrever um Job que não foi originalmente identificado como nosso.
if gcloud run jobs describe nivon-maritimo --project="$NIVON_PROJETO" --region="$REGION" --format=json >/tmp/nivon-job-existing.json 2>/dev/null; then
  python3 - <<'PY'
import json
meta=json.load(open('/tmp/nivon-job-existing.json'))
labels=(meta.get('metadata',{}).get('labels') or meta.get('labels') or {})
if labels.get('nivon-component')!='maritimo':
 raise SystemExit('JOB_EXISTENTE_SEM_LABEL_DE_PROPRIEDADE: REVISAO_MANUAL')
PY
fi
rm -f /tmp/nivon-job-existing.json
echo 'INICIANDO_BUILD_COM_CUSTO_CONTROLADO'
gcloud builds submit . --project="$NIVON_PROJETO" \
  --config=infra/google_cloud/cloudbuild.maritimo.yaml \
  --substitutions="_IMAGE_URI=$IMAGE" --quiet
echo 'PUBLICANDO_CLOUD_RUN_JOB_SEM_CRON'
gcloud run jobs deploy nivon-maritimo --project="$NIVON_PROJETO" \
  --region="$REGION" --image="$IMAGE" \
  --service-account="$NIVON_EXECUTION_SA" \
  --tasks=1 --parallelism=1 --max-retries=0 \
  --task-timeout=900s --cpu=1 --memory=1Gi \
  --labels=nivon-component=maritimo,managed-by=github-actions \
  --set-env-vars="GOOGLE_CLOUD_PROJECT=$NIVON_PROJETO,NIVON_BQ_DATASET=$NIVON_DATASET,NIVON_GCS_BUCKET=$NIVON_BUCKET,NIVON_GCP_REGION=$REGION,NIVON_MARITIMO_COLETA_HABILITADA=true,NIVON_MARITIMO_FONTES=imbituba,NIVON_PORTWATCH_COLETA_HABILITADA=true" \
  --quiet
if [ "${NIVON_EXECUTAR_PILOTO:-false}" = true ]; then
 echo 'INICIANDO_UNICO_LOTE_CLOUD_RUN'
 gcloud run jobs execute nivon-maritimo --project="$NIVON_PROJETO" \
   --region="$REGION" --wait --quiet
fi
echo 'DEPLOY_CONCLUIDO_SEM_SCHEDULER'
