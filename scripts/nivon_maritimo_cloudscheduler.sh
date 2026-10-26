#!/usr/bin/env bash
# Fail-closed: não habilita APIs, IAM nem cria conta de serviço.
set -euo pipefail
test "$NIVON_MARITIMO_AGENDAMENTO_AUTORIZADO" = true || { echo AGENDAMENTO_NAO_AUTORIZADO; exit 4; }
test "$NIVON_MARITIMO_E2E_CLOUDRUN_CONFIRMADO" = true || { echo E2E_CLOUDRUN_NAO_CONFIRMADO; exit 4; }
test "$NIVON_PROJETO" = nivon-data || { echo PROJETO_DIVERGENTE; exit 4; }
test "$NIVON_GCP_REGION" = southamerica-east1 || { echo REGIAO_DIVERGENTE; exit 4; }
test "$GITHUB_REF" = refs/heads/main || { echo EXECUCAO_APENAS_MAIN; exit 4; }
[[ "$NIVON_SCHEDULER_SA" =~ ^[a-z0-9._-]+@nivon-data\.iam\.gserviceaccount\.com$ ]] || { echo SCHEDULER_SA_INVALIDA; exit 4; }
JOB=nivon-maritimo
REGION=southamerica-east1
NAME=nivon-maritimo-6h
tmp_job="$(mktemp)"
tmp_exec="$(mktemp)"
tmp_scheduler="$(mktemp)"
trap 'rm -f "$tmp_job" "$tmp_exec" "$tmp_scheduler"' EXIT

gcloud run jobs describe "$JOB" --project="$NIVON_PROJETO" --region="$REGION" --format=json > "$tmp_job"
python3 - "$tmp_job" <<'PY'
import json,sys
obj=json.load(open(sys.argv[1]))
labels=obj.get("labels") or obj.get("metadata",{}).get("labels") or {}
if labels.get("nivon-component")!="maritimo":
    raise SystemExit("JOB_SEM_PROPRIEDADE_NIVON")
if not (obj.get("template") or obj.get("spec",{}).get("template")):
    raise SystemExit("JOB_CONTRATO_DESCONHECIDO")
print("CLOUD_RUN_JOB_VERIFICADO")
PY

gcloud run jobs executions list --job="$JOB" --project="$NIVON_PROJETO" --region="$REGION" --format=json --limit=10 > "$tmp_exec"
python3 - "$tmp_exec" <<'PY'
import json,sys
rows=json.load(open(sys.argv[1]))
passed=False
for item in rows:
    status=item.get("status",{})
    conditions=status.get("conditions",[]) or item.get("conditions",[])
    success=any(x.get("type")=="Completed" and str(x.get("status","")).lower()=="true" for x in conditions)
    failed=int(status.get("failedCount",0) or item.get("failedCount",0) or 0)
    if success and failed==0:passed=True
if not passed: raise SystemExit("CLOUD_RUN_E2E_SEM_SUCESSO_CONFIRMADO")
print("CLOUD_RUN_E2E_CONFIRMADO")
PY

gcloud iam service-accounts describe "$NIVON_SCHEDULER_SA" --project="$NIVON_PROJETO" --format='value(email)' >/dev/null
TARGET="https://run.googleapis.com/v2/projects/nivon-data/locations/southamerica-east1/jobs/nivon-maritimo:run"
if gcloud scheduler jobs describe "$NAME" --project="$NIVON_PROJETO" --location="$REGION" --format=json > "$tmp_scheduler" 2>/dev/null; then
  python3 - "$tmp_scheduler" "$TARGET" "$NIVON_SCHEDULER_SA" <<'PY'
import json,sys
data=json.load(open(sys.argv[1]))
target=data.get("httpTarget") or data.get("http_target") or {}
auth=target.get("oauthToken") or target.get("oauth_token") or {}
email=auth.get("serviceAccountEmail") or auth.get("service_account_email")
if target.get("uri")!=sys.argv[2] or email!=sys.argv[3]:
    raise SystemExit("SCHEDULER_EXISTENTE_DIVERGENTE")
print("SCHEDULER_EXISTENTE_SEM_ALTERACOES")
PY
  exit 0
fi
gcloud scheduler jobs create http "$NAME" --project="$NIVON_PROJETO" --location="$REGION" \
  --schedule='12 */6 * * *' --time-zone='Etc/UTC' --uri="$TARGET" \
  --http-method=POST --message-body='{}' --headers='Content-Type=application/json' \
  --oauth-service-account-email="$NIVON_SCHEDULER_SA" \
  --oauth-token-scope='https://www.googleapis.com/auth/cloud-platform' --quiet
echo SCHEDULER_CRIADO_COM_APROVACAO_E_E2E
