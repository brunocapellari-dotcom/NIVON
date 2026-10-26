#!/usr/bin/env bash
# Aceite final do NIVON Cloud Run privado APÓS deploy manual aprovado.
# Consulta somente metadados, healthz e ANTT BigQuery com token temporário.
# Não concede IAM, não ativa serviços, não modifica Cloud.
set -euo pipefail

[[ "${GITHUB_REF:-}" == "refs/heads/main" ]] || { echo 'BLOQUEADO_FORA_DA_MAIN'; exit 3; }
[[ "${NIVON_GO_LIVE_DEPLOY_APPROVED:-}" == true &&
   "${NIVON_GCP_COST_REVIEWED:-}" == true ]] || {
    echo 'BLOQUEADO_CUSTO_OU_DEPLOY_NAO_APROVADO'; exit 3;
}
[[ "${NIVON_PROJETO:-}" == nivon-data &&
   "${NIVON_DATASET:-}" == nivon_raw ]] || { echo 'PROJETO_GCP_INVALIDO'; exit 3; }
[[ "${GITHUB_SHA:-}" =~ ^[a-f0-9]{40}$ ]] || { echo 'COMMIT_GIT_INVALIDO'; exit 3; }
command -v gcloud >/dev/null || { echo 'GCLOUD_NAO_DISPONIVEL'; exit 3; }
command -v curl >/dev/null || { echo 'CURL_NAO_DISPONIVEL'; exit 3; }
: "${PYTHONPATH:=src}"
export PYTHONPATH
REGION=southamerica-east1
SERVICE=nivon-terminal
TEMP="$(mktemp -d)"
chmod 700 "$TEMP"
trap 'rm -rf "$TEMP"' EXIT

gcloud run services describe "$SERVICE" \
  --project="$NIVON_PROJETO" --region="$REGION" --format=json > "$TEMP/service.json"
gcloud run services get-iam-policy "$SERVICE" \
  --project="$NIVON_PROJETO" --region="$REGION" --format=json > "$TEMP/iam.json"

# A URL vem da resposta de metadados GCP, porém é validada antes de qualquer HTTP.
URL="$(python - "$TEMP/service.json" <<'PY'
import json,sys
from nivon.aceite_terminal_privado import _url_privada
doc=json.load(open(sys.argv[1],encoding="utf-8"))
print(_url_privada((doc.get("status") or {}).get("url")))
PY
)"
[[ "$URL" == https://* ]] || { echo 'URL_INVALIDA'; exit 3; }

# Prova de privacidade: Cloud Run não pode atender sem IAM.
STATUS_UNAUTH="$(curl --silent --show-error --connect-timeout 8 --max-time 20 \
  -o "$TEMP/unauth.body" -w '%{http_code}' "$URL/healthz")"
[[ "$STATUS_UNAUTH" == 401 || "$STATUS_UNAUTH" == 403 ]] || {
    echo 'GO_LIVE_BLOQUEADO_URL_NAO_PRIVADA'; exit 3;
}

# Token só em memória, nunca em arquivos, logs, manifests ou resumos.
IDENTITY_TOKEN="$(gcloud auth print-identity-token --audiences="$URL")"
[[ "${#IDENTITY_TOKEN}" -gt 80 ]] || { echo 'TOKEN_IDENTIDADE_NAO_EMITIDO'; exit 3; }
HTTP_HEALTH="$(curl --silent --show-error --connect-timeout 10 --max-time 40 \
  -H "Authorization: Bearer $IDENTITY_TOKEN" \
  -o "$TEMP/health.json" -w '%{http_code}' "$URL/healthz")"
[[ "$HTTP_HEALTH" == 200 ]] || { echo 'HEALTH_PRIVADO_NAO_ACESSIVEL'; exit 3; }
HTTP_DADOS="$(curl --silent --show-error --connect-timeout 10 --max-time 105 \
  -H "Authorization: Bearer $IDENTITY_TOKEN" \
  -o "$TEMP/dados.json" -w '%{http_code}' "$URL/api/v1/ferrovia")"
unset IDENTITY_TOKEN
[[ "$HTTP_DADOS" == 200 ]] || { echo 'ANTT_REAL_NAO_ACESSIVEL'; exit 3; }

python -m nivon.aceite_terminal_privado \
  --service "$TEMP/service.json" \
  --iam "$TEMP/iam.json" \
  --health "$TEMP/health.json" \
  --dados "$TEMP/dados.json" \
  --unauth-status "$STATUS_UNAUTH" \
  --commit-sha "$GITHUB_SHA"
echo 'NIVON_GO_LIVE_PRIVADO_01_VERIFICADO=SIM'
