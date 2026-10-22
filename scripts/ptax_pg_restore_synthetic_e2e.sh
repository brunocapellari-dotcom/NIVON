#!/usr/bin/env bash
# PostgreSQL E2E REAL somente com dados SINTETICOS e container temporario.
# Docker sem rede/portas/volumes. Nao conecta Neon, GCP ou bancos externos.
set -euo pipefail
if [[ "$#" -ne 1 || "$1" != "--run-synthetic" ]]; then
  echo "Modo seguro: bash scripts/ptax_pg_restore_synthetic_e2e.sh --run-synthetic" >&2
  exit 2
fi
if ! command -v docker >/dev/null || ! command -v python3 >/dev/null; then
  echo "Docker e Python3 sao obrigatorios." >&2
  exit 2
fi
cd "$(dirname "$0")/.."
if [[ ! -f tests/fixtures/ptax_postgres17_synthetic.sql ]]; then
  echo "Fixture sintetica ausente." >&2
  exit 2
fi
container="nivon-ptax-restore-ci-$$"
cleanup() { docker rm --force "$container" >/dev/null 2>&1 || true; }
trap cleanup EXIT

# A imagem publica e obtida pelo runner; o container nao tem rede ativa.
docker run --detach --rm --network none --name "$container" \
  -e POSTGRES_PASSWORD="NIVON_SYNTHETIC_ONLY_NO_REAL_CREDENTIALS" \
  postgres:17-bookworm >/dev/null

ready=0
for attempt in $(seq 1 50); do
  if docker exec "$container" pg_isready -q -U postgres; then
    ready=1
    break
  fi
  sleep 1
done
if [[ "$ready" != "1" ]]; then
  echo "PostgreSQL sintetico nao iniciou." >&2
  exit 1
fi
docker exec "$container" createdb -U postgres nivon
docker exec -i "$container" psql -X -q -v ON_ERROR_STOP=1 \
  -U postgres -d nivon < tests/fixtures/ptax_postgres17_synthetic.sql

# Reproduz as flags e os objetos do script versionado de pg_dump.
docker exec "$container" pg_dump -U postgres --dbname=nivon --format=custom \
  --no-owner --no-acl --no-password --serializable-deferrable \
  --lock-wait-timeout=5000 --file=/tmp/nivon_ptax_ci.pgcustom \
  --table=public.nivon_ptax_quotes \
  --table=public.nivon_ptax_runs \
  --table=public.nivon_ptax_checkpoints \
  --table=public.nivon_ptax_quotes_id_seq \
  --table=public.nivon_ptax_runs_id_seq

# TOC conferido pelo MESMO parser usado no pacote de backup NIVON.
docker exec "$container" pg_restore --list /tmp/nivon_ptax_ci.pgcustom | \
  PYTHONPATH=scripts python3 -c 'import sys; from ptax_postgres_native_backup import _analyze_toc; toc=_analyze_toc(sys.stdin.read()); assert len(toc["TABLE"])==3 and len(toc["TABLE DATA"])==3 and len(toc["SEQUENCE SET"])==2'

docker exec "$container" createdb -U postgres nivon_restore_check
docker exec "$container" pg_restore -U postgres \
  --dbname=nivon_restore_check --no-owner --no-acl --exit-on-error \
  /tmp/nivon_ptax_ci.pgcustom

# Compara integralmente linhas, metadados, NUMERIC e last_value de sequencias.
query="$(cat <<'SQL'
SELECT jsonb_build_object(
 'quotes',(SELECT jsonb_agg(to_jsonb(q) ORDER BY id) FROM public.nivon_ptax_quotes q),
 'runs',(SELECT jsonb_agg(to_jsonb(r) ORDER BY id) FROM public.nivon_ptax_runs r),
 'checkpoints',(SELECT jsonb_agg(to_jsonb(c) ORDER BY currency,window_start,window_end) FROM public.nivon_ptax_checkpoints c),
 'quotes_sequence',(SELECT last_value FROM public.nivon_ptax_quotes_id_seq),
 'runs_sequence',(SELECT last_value FROM public.nivon_ptax_runs_id_seq),
 'indexes',(SELECT jsonb_agg(jsonb_build_object('name',indexname,'ddl',indexdef) ORDER BY indexname)
              FROM pg_indexes WHERE schemaname='public' AND tablename IN
              ('nivon_ptax_quotes','nivon_ptax_runs','nivon_ptax_checkpoints')),
 'constraints',(SELECT jsonb_agg(jsonb_build_object('table_name',cl.relname,'name',co.conname,'definition',pg_get_constraintdef(co.oid)) ORDER BY cl.relname,co.conname)
                  FROM pg_constraint co JOIN pg_class cl ON cl.oid=co.conrelid
                  JOIN pg_namespace ns ON ns.oid=cl.relnamespace
                  WHERE ns.nspname='public' AND cl.relname IN
                  ('nivon_ptax_quotes','nivon_ptax_runs','nivon_ptax_checkpoints'))
)::text;
SQL
)"
source_fingerprint="$(
 docker exec "$container" psql -X -A -t -v ON_ERROR_STOP=1 -U postgres -d nivon -c "$query" | sha256sum | cut -d ' ' -f1
)"
restored_fingerprint="$(
 docker exec "$container" psql -X -A -t -v ON_ERROR_STOP=1 -U postgres -d nivon_restore_check -c "$query" | sha256sum | cut -d ' ' -f1
)"
if [[ "$source_fingerprint" != "$restored_fingerprint" ]]; then
  echo "Dados ou sequencias do banco sintetico restaurado divergem." >&2
  exit 1
fi
counts="$(
 docker exec "$container" psql -X -A -t -v ON_ERROR_STOP=1 -U postgres -d nivon_restore_check -c \
  "SELECT (SELECT count(*) FROM public.nivon_ptax_quotes)::text || ':' || (SELECT count(*) FROM public.nivon_ptax_runs)::text || ':' || (SELECT count(*) FROM public.nivon_ptax_checkpoints)::text;"
)"
if [[ "$counts" != "3:2:2" ]]; then
  echo "Contagens sinteticas inesperadas." >&2
  exit 1
fi

# Reutiliza a auditoria read-only versionada (mesma consulta em cada banco).
# Ignorar somente a hora de execução do relatório, que varia entre consultas.
audit_normalize() {
  python3 -c 'import sys,json; obj=json.load(sys.stdin)["source_audit_manifest"]; obj.pop("snapshot_timestamp_utc",None); assert obj["invalid_prices"]==0 and obj["duplicate_business_keys"]==0 and obj["invalid_timestamps"]==0; print(json.dumps(obj,sort_keys=True,separators=(",",":")))'
}
source_audit="$(
  docker exec -i "$container" psql -X -A -t -v ON_ERROR_STOP=1 -U postgres -d nivon \
    < database/neon_ptax_readonly_audit.sql | audit_normalize
)"
restored_audit="$(
  docker exec -i "$container" psql -X -A -t -v ON_ERROR_STOP=1 -U postgres -d nivon_restore_check \
    < database/neon_ptax_readonly_audit.sql | audit_normalize
)"
if [[ "$source_audit" != "$restored_audit" ]]; then
  echo "Auditoria de agregados da restauracao sintetica divergiu." >&2
  exit 1
fi
printf 'POSTGRES17_SYNTHETIC_RESTORE_OK; quotes=3; runs=2; checkpoints=2; sequences=2; production_restore_verified=false\n'
