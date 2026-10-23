#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
export PYTHONPATH="$PWD/src"
if [[ $# -gt 0 && "$1" == "doctor" ]]; then
  exec python -m nivon.ferramentas doctor
elif [[ $# -gt 0 && "$1" == "preflight" ]]; then
  exec python -m nivon.preparacao_host check
elif [[ $# -gt 0 && "$1" == "plan" ]]; then
  exec python -m nivon.planejador preview --github
elif [[ $# -gt 0 && "$1" == "status" ]]; then
  exec python -m nivon.autonomia status
elif [[ $# -gt 0 && "$1" == "stop" ]]; then
  exec python -m nivon.autonomia stop
elif [[ $# -gt 0 && "$1" == "night-status" ]]; then
  exec python -m nivon.janela_noturna status
elif [[ $# -gt 0 && "$1" == "quality" ]]; then
  exec python -m nivon.qualidade --json
elif [[ $# -gt 0 && "$1" == "metrics" ]]; then
  exec python -m nivon.cooperacao metrics
elif [[ $# -gt 0 && "$1" == "dueto" ]]; then
  exec python -m nivon.dueto_painel json
elif [[ $# -gt 0 && "$1" == "painel" ]]; then
  exec python -m nivon.dueto_painel html
elif [[ $# -gt 0 && "$1" == "painel-live" ]]; then
  exec python -m nivon.dueto_painel watch --interval 15 --minutes 120
elif [[ $# -gt 0 && "$1" == "efficiency" ]]; then
  exec python -m nivon.indicadores_engenharia report
elif [[ $# -gt 0 && "$1" == "integration-check" ]]; then
  exec python -m nivon.integracao_branch check
elif [[ $# -gt 0 && "$1" == "run" ]]; then
  python -m nivon.janela_noturna check
  python -m nivon.planejador refresh --github
  exec python -m nivon.autonomia run --minutes 120 --max-tasks 8 --per-task 15
elif [[ $# -gt 0 ]]; then
  echo "Uso: bash scripts/nivon-autonomo.sh [doctor|preflight|plan|quality|dueto|painel|painel-live|metrics|efficiency|integration-check|night-status|run|status|stop]" >&2
  exit 2
fi
python -m nivon.janela_noturna check
python -m nivon.planejador refresh --github
exec python -m nivon.autonomia start --minutes 120 --max-tasks 8 --per-task 15
