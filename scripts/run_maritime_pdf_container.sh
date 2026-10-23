#!/usr/bin/env bash
# Manual, fail-closed local runner. No download or network access at runtime.
# Usage:
#   bash scripts/run_maritime_pdf_container.sh INPUT_DIR OUTPUT_DIR \
#       manifest.json audit_001.json 2026-10-23T12:00:00-04:00 [--commit]
set -euo pipefail

if [[ $# -lt 5 || $# -gt 6 ]]; then
  echo "Usage: $0 INPUT_DIR OUTPUT_DIR MANIFEST_NAME REPORT_NAME AS_OF [--commit]" >&2
  exit 2
fi
INPUT_DIR=$1
OUTPUT_DIR=$2
MANIFEST_NAME=$3
REPORT_NAME=$4
AS_OF=$5
MODE=${6:-}

if [[ -n "${MODE}" && "${MODE}" != "--commit" ]]; then
  echo "Only explicit --commit is supported; dry-run is the default" >&2
  exit 2
fi
for BASENAME in "${MANIFEST_NAME}" "${REPORT_NAME}"; do
  if [[ "${BASENAME}" == "." || "${BASENAME}" == ".." || "${BASENAME}" == */* || "${BASENAME}" == *\\* ]]; then
    echo "Manifest and report filenames must be basenames, no paths" >&2
    exit 2
  fi
done
if [[ "${MANIFEST_NAME}" != *.json || "${REPORT_NAME}" != *.json ]]; then
  echo "Manifest and report must be JSON files" >&2
  exit 2
fi
if [[ ! -d "${INPUT_DIR}" || ! -d "${OUTPUT_DIR}" ]]; then
  echo "Input and output directories must already exist" >&2
  exit 2
fi
INPUT_ABS=$(cd -- "${INPUT_DIR}" && pwd -P)
OUTPUT_ABS=$(cd -- "${OUTPUT_DIR}" && pwd -P)
if [[ "${INPUT_ABS}" == "${OUTPUT_ABS}" || ! -f "${INPUT_ABS}/${MANIFEST_NAME}" ]]; then
  echo "Input and output must be distinct; manifest must exist" >&2
  exit 2
fi
if [[ -e "${OUTPUT_ABS}/${REPORT_NAME}" ]]; then
  echo "Audit report already exists; no overwrites" >&2
  exit 2
fi
if ! command -v docker >/dev/null 2>&1; then
  echo "Docker must be installed and image built manually before running" >&2
  exit 2
fi

COMMAND=(
  --as-of "${AS_OF}"
  --report "/output/${REPORT_NAME}"
)
if [[ "${MODE}" == "--commit" ]]; then
  COMMAND+=(--commit --ack-rights --db /output/maritime.sqlite)
fi

exec docker run --rm --pull never \
  --network none --read-only \
  --cap-drop ALL --security-opt no-new-privileges:true \
  --pids-limit 40 --memory 1536m --cpus 1.5 \
  --tmpfs /tmp:rw,nosuid,noexec,size=64m \
  --user "$(id -u):$(id -g)" \
  --mount "type=bind,source=${INPUT_ABS},target=/inputs,readonly" \
  --mount "type=bind,source=${OUTPUT_ABS},target=/output" \
  nivon-maritime-pdf-offline:local \
  "/inputs/${MANIFEST_NAME}" "${COMMAND[@]}"
