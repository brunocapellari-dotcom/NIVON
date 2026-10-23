#!/usr/bin/env bash
# NIVON: projeto Google Cloud vazio. Nunca conecta billing, cria buckets ou executa consultas.
set -euo pipefail

usage() {
  cat <<'HELP'
NIVON — bootstrap seguro do projeto Google Cloud
  ./scripts/bootstrap_gcp_project.sh --check PROJECT_ID
  ./scripts/bootstrap_gcp_project.sh --create PROJECT_ID

--check: apenas leitura (consulta metadados e billing).
--create: cria projeto vazio SEM billing e SEM APIs opcionais.
Requer Google Cloud CLI autenticado. Nunca use chaves de servico aqui.
ID do projeto: 6-30 caracteres, letras minusculas, digitos e hifens.
HELP
}

if [[ $# -ne 2 ]]; then usage; exit 2; fi
MODE="$1"
PROJECT_ID="$2"
if [[ "$MODE" != "--check" && "$MODE" != "--create" ]]; then usage; exit 2; fi
if [[ ! "$PROJECT_ID" =~ ^[a-z][a-z0-9-]{4,28}[a-z0-9]$ ]]; then
  echo "ID de projeto inválido. Escolha 6 a 30 caracteres válidos." >&2
  exit 2
fi
if ! command -v gcloud >/dev/null 2>&1; then
  echo "Instale Google Cloud CLI ou utilize o Cloud Shell." >&2
  exit 1
fi
if ! command -v python3 >/dev/null 2>&1; then
  echo "Python 3 é necessário para validar a resposta de faturamento." >&2
  exit 1
fi
ACTIVE_ACCOUNT="$(gcloud auth list --filter='status:ACTIVE' --format='value(account)' 2>/dev/null)"
if [[ -z "$ACTIVE_ACCOUNT" ]]; then
  echo "Nenhuma conta Google Cloud autenticada. Use gcloud auth login." >&2
  exit 1
fi
echo "Conta ativa: $ACTIVE_ACCOUNT"
echo "Projeto alvo: $PROJECT_ID"

if [[ "$MODE" == "--create" ]]; then
  if gcloud projects describe "$PROJECT_ID" --format='value(projectId)' >/dev/null 2>&1; then
    echo "Projeto já visível; não vamos criar ou sobrescrever." >&2
    exit 1
  fi
  echo "Confirme o ID exato para criar apenas o projeto (sem billing, sem recursos):"
  read -r CONFIRMATION
  if [[ "$CONFIRMATION" != "$PROJECT_ID" ]]; then
    echo "Confirmação divergente: nenhuma alteração executada." >&2
    exit 1
  fi
  gcloud projects create "$PROJECT_ID" \
    --name="NIVON - Plataforma de Dados" \
    --labels=project=nivon,environment=bootstrap \
    --no-enable-cloud-apis
fi

# Falhas de visibilidade/permissão são bloqueantes: nunca presumir que billing = false.
ACTUAL_ID="$(gcloud projects describe "$PROJECT_ID" --format='value(projectId)')"
if [[ "$ACTUAL_ID" != "$PROJECT_ID" ]]; then
  echo "O projeto retornado não corresponde ao ID solicitado." >&2
  exit 1
fi

if ! BILLING_JSON="$(gcloud billing projects describe "$PROJECT_ID" --format=json 2>/dev/null)"; then
  echo "Não foi possível verificar a situação do faturamento: estado INDETERMINADO." >&2
  exit 1
fi
BILLING_ENABLED="$(printf '%s' "$BILLING_JSON" | python3 -c '
import json,sys
obj=json.load(sys.stdin)
v=obj.get("billingEnabled")
print("true" if v is True else "false" if v is False else "unknown")
')"
if [[ "$BILLING_ENABLED" != "false" ]]; then
  echo "BLOQUEIO: faturamento ativo ou indeterminado ($BILLING_ENABLED)." >&2
  echo "Nenhum bucket, API opcional, serviço ou job foi criado por este script." >&2
  exit 1
fi

echo "PROJETO IDENTIFICADO: $ACTUAL_ID"
echo "BILLING: DESATIVADO (resposta oficial)"
echo "Nenhuma API opcional, banco, bucket, Cloud Run, dataset ou job foi provisionado."
echo "Próxima etapa: auditoria IAM/cotas e teste sandbox não persistente, separadamente."
