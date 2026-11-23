#!/usr/bin/env bash
# Arquiva branches antigas do NIVON em tags arquivo/<nome> e só então as apaga.
# Mantém a main e as branches de PRs abertas. Por padrão só lista (simulação);
# com --executar cria as tags, confere que existem no GitHub e apaga as branches.
# Rodar num clone com permissão de push (ex.: Cloud Shell ou computador do responsável).
# Recuperar depois: git fetch origin tag arquivo/<nome> && git switch -c <nome> arquivo/<nome>
set -euo pipefail
REPO=brunocapellari-dotcom/NIVON
EXECUTAR=false
[[ "${1:-}" == "--executar" ]] && EXECUTAR=true
git remote get-url origin | grep -qi "brunocapellari-dotcom/nivon" || { echo "Rode dentro do clone do NIVON"; exit 3; }

manter=$(mktemp); arquivar=$(mktemp); trap 'rm -f "$manter" "$arquivar"' EXIT
echo main > "$manter"
curl -fsS "https://api.github.com/repos/$REPO/pulls?state=open&per_page=100" |
  python3 -c 'import json,sys
for p in json.load(sys.stdin):
    r = p["head"]["repo"]
    if r and r["full_name"].lower() == "brunocapellari-dotcom/nivon":
        print(p["head"]["ref"])' >> "$manter"
git fetch --quiet --prune origin '+refs/heads/*:refs/remotes/origin/*'
git for-each-ref --format='%(refname:lstrip=3)' refs/remotes/origin |
  grep -vx HEAD | grep -vxFf "$manter" > "$arquivar" || true
echo "Mantidas ($(wc -l < "$manter")):"; sed 's/^/  /' "$manter"
echo "A arquivar e apagar: $(wc -l < "$arquivar") branches"
$EXECUTAR || { sed 's/^/  /' "$arquivar"; echo; echo "Simulação. Para executar: bash scripts/arquivar_branches.sh --executar"; exit 0; }

echo "1/3 Criando tags arquivo/<nome> (sobrescreve nada que já exista)"
while read -r b; do
  git rev-parse -q --verify "refs/tags/arquivo/$b" >/dev/null || git tag "arquivo/$b" "refs/remotes/origin/$b"
done < "$arquivar"
sed 's#^#refs/tags/arquivo/#' "$arquivar" | xargs -n 50 git push --quiet origin

echo "2/3 Conferindo as tags no GitHub antes de apagar qualquer branch"
remotas=$(git ls-remote --tags origin 'refs/tags/arquivo/*' | awk '{print $1" "$2}')
while read -r b; do
  sha=$(git rev-parse "refs/remotes/origin/$b")
  grep -qxF "$sha refs/tags/arquivo/$b" <<< "$remotas" || { echo "TAG AUSENTE OU DIVERGENTE: $b — nada foi apagado"; exit 4; }
done < "$arquivar"

echo "3/3 Apagando as branches arquivadas"
sed 's#^#:refs/heads/#' "$arquivar" | xargs -n 50 git push --quiet origin
echo "CONCLUIDO: $(wc -l < "$arquivar") branches arquivadas em tags arquivo/<nome> e apagadas."
