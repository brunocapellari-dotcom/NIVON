#!/usr/bin/env bash
# NIVON: executar E2E de 3 jobs em imagem selecionada, ambiente efêmero offline.
# Nunca habilitar este script como job real ou coletor; sem rede/deploy/credenciais.
set -euo pipefail

test "$#" -eq 3 || { echo "BATCH_ARGS_INVALID"; exit 2; }
analytics_image="$1"
platform="$2"
variant="$3"
case "$analytics_image:$variant" in
  "nivon-analytics:ci:trixie"|"nivon-analytics:distroless:distroless") ;;
  *) echo "BATCH_IMAGE_NOT_ALLOWED"; exit 2 ;;
esac
case "$platform" in linux/amd64|linux/arm64) ;; *) exit 2 ;; esac
: "${RUNNER_TEMP:?RUNNER_TEMP required}"
state="$RUNNER_TEMP/nivon-batch-$variant-state"
backup="$RUNNER_TEMP/nivon-batch-$variant-backup"
restore="$RUNNER_TEMP/nivon-batch-$variant-restore"
for d in "$state" "$backup" "$restore"; do
  test ! -e "$d" || { echo "BATCH_REQUIRES_FRESH_STATE"; exit 2; }
  sudo install -d -o 65532 -g 65532 -m 0700 "$d"
done

docker pull --platform "$platform" \
  python:3.11.17-alpine3.23@sha256:924d53e01cee5204d35fbcfb71b6c1568c857d7c31141f960ff6a37e111ecc7f > /dev/null
if ! docker image inspect nivon-batch:worker > /dev/null 2>&1; then
  docker build --network=none --platform "$platform" \
    -f infra/docker/Dockerfile.worker-alpine -t nivon-batch:worker . > /dev/null
fi

batch_cmd() {
  local image="$1" root="$2" stage="$3"
  shift 3
  docker run --rm --platform "$platform" --network none --read-only \
    --cap-drop ALL --security-opt no-new-privileges:true \
    --user 65532:65532 --pids-limit 96 --memory 1024m --cpus 1.0 \
    --tmpfs /tmp:rw,nosuid,nodev,size=192m,uid=65532,gid=65532 \
    --mount "type=bind,source=$root,target=/var/lib/nivon/state" \
    --mount "type=bind,source=$backup,target=/var/lib/nivon/backups" \
    -e NIVON_OFFLINE_STATE_DIR=/var/lib/nivon/state \
    -e NIVON_OFFLINE_BACKUP_DIR=/var/lib/nivon/backups \
    -e NIVON_RUNTIME_ENABLED=false -e NIVON_BACKUP_ENABLED=false \
    -e NIVON_COLLECTORS_ENABLED=false -e NIVON_PUBLICATION_ENABLED=false \
    -e NUMBA_NUM_THREADS=1 -e OPENBLAS_NUM_THREADS=1 \
    -e OMP_NUM_THREADS=1 -e NUMBA_CACHE_DIR=/tmp/numba \
    --entrypoint /usr/local/bin/python "$image" \
    -m nivon.infra_offline_pipeline --stage "$stage" "$@"
}

batch_cmd nivon-batch:worker "$state" prepare
batch_cmd nivon-batch:worker "$state" prepare
set +e
batch_cmd "$analytics_image" "$state" process --interrupt-after-lease
crash_code="$?"
set -e
test "$crash_code" -eq 3
batch_cmd nivon-batch:worker "$state" reconcile
batch_cmd "$analytics_image" "$state" process
batch_cmd "$analytics_image" "$state" process
batch_cmd nivon-batch:worker "$state" verify
batch_cmd nivon-batch:worker "$state" backup
batch_cmd nivon-batch:worker "$restore" restore
batch_cmd nivon-batch:worker "$restore" verify
batch_cmd "$analytics_image" "$restore" process

echo "NIVON_BATCH_INTERWORKER_CRASH_RESTORE_OK variant=$variant"
echo "NIVON_2_WORKERS_3_JOBS_CRASH_RESTORE_E2E_OK_NO_DEPLOY"
