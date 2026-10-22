#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
export PYTHONPATH="$PWD/src"
if [[ $# -gt 0 && "$1" == "status" ]]; then
  exec python -m nivon.autonomia status
elif [[ $# -gt 0 && "$1" == "stop" ]]; then
  exec python -m nivon.autonomia stop
elif [[ $# -gt 0 && "$1" == "run" ]]; then
  python -m nivon.cooperacao seed docs/COOPERACAO_TAREFAS.json
  exec python -m nivon.autonomia run --minutes 120 --max-tasks 8 --per-task 15
elif [[ $# -gt 0 ]]; then
  echo "Uso: bash scripts/nivon-autonomo.sh [run|status|stop]" >&2
  exit 2
fi
python -m nivon.cooperacao seed docs/COOPERACAO_TAREFAS.json
exec python -m nivon.autonomia start --minutes 120 --max-tasks 8 --per-task 15
