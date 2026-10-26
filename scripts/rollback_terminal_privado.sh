#!/usr/bin/env bash
# Reversão MANUAL de tráfego Cloud Run para revisão previamente verificada.
# Não aplica sem três confirmações explícitas. Não modifica IAM ou billing.
set -euo pipefail
[[ "${GITHUB_REF:-}" == refs/heads/main ]] || { echo 'ROLLBACK_SOMENTE_MAIN'; exit 3; }
[[ "${NIVON_ROLLBACK_APPROVED:-}" == true &&
   "${NIVON_GCP_COST_REVIEWED:-}" == true &&
   "${NIVON_GO_LIVE_DEPLOY_APPROVED:-}" == true ]] || {
    echo 'ROLLBACK_SEM_APROVACAO'; exit 3;
}
[[ "${NIVON_PROJETO:-}" == nivon-data ]] || { echo 'PROJETO_DIVERGENTE'; exit 3; }
REV="${NIVON_ROLLBACK_TARGET_REVISION:-}"
[[ "$REV" =~ ^nivon-terminal-[a-z0-9-]{5,90}$ ]] || {
    echo 'REVISAO_ROLLBACK_INVALIDA'; exit 3;
}
REGION=southamerica-east1
SVC=nivon-terminal
TEMP="$(mktemp -d)"
trap 'rm -rf "$TEMP"' EXIT

gcloud run services get-iam-policy "$SVC" --project="$NIVON_PROJETO" \
  --region="$REGION" --format=json > "$TEMP/iam.json"
gcloud run services describe "$SVC" --project="$NIVON_PROJETO" \
  --region="$REGION" --format=json > "$TEMP/service.json"
gcloud run revisions describe "$REV" --project="$NIVON_PROJETO" \
  --region="$REGION" --format=json > "$TEMP/revision.json"

python - "$TEMP/iam.json" "$TEMP/service.json" "$TEMP/revision.json" "$REV" <<'PY'
import json,sys
iam,service,revision=(json.load(open(name)) for name in sys.argv[1:4])
expected=sys.argv[4]
if (service.get("metadata",{}).get("name")!="nivon-terminal"
    or service.get("metadata",{}).get("labels",{}).get("nivon-component")!="terminal"):
    raise SystemExit("ROLLBACK_SERVICO_SEM_POSSE_NIVON")
for binding in iam.get("bindings",[]):
    if binding.get("role")=="roles/run.invoker" and set(
        binding.get("members",[]))&{"allUsers","allAuthenticatedUsers"}:
        raise SystemExit("ROLLBACK_IAM_PUBLICO")
meta=revision.get("metadata",{})
if meta.get("name")!=expected:
    raise SystemExit("ROLLBACK_REVISAO_DIVERGENTE")
labels=meta.get("labels") or {}
if labels.get("serving.knative.dev/service") not in (None,"nivon-terminal"):
    raise SystemExit("ROLLBACK_REVISAO_OUTRO_SERVICO")
conditions=(revision.get("status") or {}).get("conditions") or []
if not any(x.get("type")=="Ready" and x.get("status") in ("True",True)
           for x in conditions):
    raise SystemExit("ROLLBACK_REVISAO_NAO_PRONTA")
PY

echo 'ATUALIZANDO_TRAFEGO_PARA_REVISAO_AUTORIZADA'
gcloud run services update-traffic "$SVC" \
  --project="$NIVON_PROJETO" --region="$REGION" \
  --to-revisions="$REV=100" --quiet
echo 'ROLLBACK_APLICADO_CONFERIR_IAM_E_API_AUTENTICADA'
