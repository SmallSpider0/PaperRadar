#!/usr/bin/env bash
set -euo pipefail

log() {
  printf '[paperradar] %s\n' "$*"
}

export PAPERRADAR_HOME="${PAPERRADAR_HOME:-/opt/paperradar}"
export PGDATA="${PGDATA:-/var/lib/postgresql/data}"
export PAPERRADAR_APP_HOST="${PAPERRADAR_APP_HOST:-0.0.0.0}"
export PAPERRADAR_APP_PORT="${PAPERRADAR_APP_PORT:-8080}"
export PAPERRADAR_STATIC_DIR="${PAPERRADAR_STATIC_DIR:-$PAPERRADAR_HOME/app/frontend/out}"
export PAPERRADAR_DB_HOST="${PAPERRADAR_DB_HOST:-127.0.0.1}"
export PAPERRADAR_DB_PORT="${PAPERRADAR_DB_PORT:-5432}"
export PAPERRADAR_DB_NAME="${PAPERRADAR_DB_NAME:-paperradar}"
export PAPERRADAR_DB_USER="${PAPERRADAR_DB_USER:-paperradar}"
export PAPERRADAR_DB_PASSWORD="${PAPERRADAR_DB_PASSWORD:-paperradar}"
export PAPERRADAR_REDIS_URL="${PAPERRADAR_REDIS_URL:-redis://127.0.0.1:6379/0}"
export PAPERRADAR_ADMIN_USERNAME="${PAPERRADAR_ADMIN_USERNAME:-admin}"
export PAPERRADAR_ADMIN_PASSWORD="${PAPERRADAR_ADMIN_PASSWORD:-paperradar}"
export PAPERRADAR_AUTH_COOKIE_SECURE="${PAPERRADAR_AUTH_COOKIE_SECURE:-false}"
export PAPERRADAR_AUTO_IMPORT_SEED="${PAPERRADAR_AUTO_IMPORT_SEED:-true}"
export PAPERRADAR_SEED_PATH="${PAPERRADAR_SEED_PATH:-$PAPERRADAR_HOME/data/seed/paperradar-paperdata.sql.gz}"

if [[ ! "$PAPERRADAR_DB_NAME" =~ ^[A-Za-z_][A-Za-z0-9_]*$ ]]; then
  log "invalid PAPERRADAR_DB_NAME: use only letters, numbers and underscore"
  exit 1
fi
if [[ ! "$PAPERRADAR_DB_USER" =~ ^[A-Za-z_][A-Za-z0-9_]*$ ]]; then
  log "invalid PAPERRADAR_DB_USER: use only letters, numbers and underscore"
  exit 1
fi
PGPASSWORD_SQL="${PAPERRADAR_DB_PASSWORD//\'/\'\'}"

PG_BIN="$(find /usr/lib/postgresql -maxdepth 5 -type f -name initdb -printf '%h\n' | sort -V | tail -1)"
export PATH="$PG_BIN:$PATH"

if [ ! -s "$PGDATA/PG_VERSION" ]; then
  log "initializing PostgreSQL data directory: $PGDATA"
  install -d -o postgres -g postgres "$PGDATA"
  runuser -u postgres -- initdb -D "$PGDATA" --encoding=UTF8 --locale=C.UTF-8 >/dev/null
  cat >> "$PGDATA/postgresql.conf" <<PGCONF
listen_addresses = '127.0.0.1'
port = ${PAPERRADAR_DB_PORT}
PGCONF
  cat >> "$PGDATA/pg_hba.conf" <<'PGHBA'
host all all 127.0.0.1/32 scram-sha-256
host all all ::1/128 scram-sha-256
PGHBA
fi

log "starting PostgreSQL"
runuser -u postgres -- pg_ctl -D "$PGDATA" -w start >/dev/null

log "ensuring database and user exist"
runuser -u postgres -- psql -v ON_ERROR_STOP=1 <<SQL
DO \$\$
BEGIN
  IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = '${PAPERRADAR_DB_USER}') THEN
    CREATE ROLE ${PAPERRADAR_DB_USER} LOGIN PASSWORD '${PGPASSWORD_SQL}';
  ELSE
    ALTER ROLE ${PAPERRADAR_DB_USER} WITH PASSWORD '${PGPASSWORD_SQL}';
  END IF;
END
\$\$;
SELECT 'CREATE DATABASE ${PAPERRADAR_DB_NAME} OWNER ${PAPERRADAR_DB_USER}'
WHERE NOT EXISTS (SELECT FROM pg_database WHERE datname = '${PAPERRADAR_DB_NAME}')\gexec
SQL

log "starting Redis"
redis-server --daemonize yes --bind 127.0.0.1 --port 6379 --save "" --appendonly no

log "applying database schema"
cd "$PAPERRADAR_HOME/app"
PYTHONPATH=. python3 scripts/apply_schema.py

if [ "$PAPERRADAR_AUTO_IMPORT_SEED" = "true" ] && [ -f "$PAPERRADAR_SEED_PATH" ]; then
  paper_count="$(PGPASSWORD="$PAPERRADAR_DB_PASSWORD" psql -h "$PAPERRADAR_DB_HOST" -p "$PAPERRADAR_DB_PORT" -U "$PAPERRADAR_DB_USER" -d "$PAPERRADAR_DB_NAME" -Atc "SELECT COUNT(*) FROM papers;" 2>/dev/null || echo 0)"
  if [ "${paper_count:-0}" = "0" ]; then
    log "importing bundled paper seed: $PAPERRADAR_SEED_PATH"
    PYTHONPATH=. python3 scripts/import_seed.py >/tmp/paperradar-seed-import.log 2>&1 || {
      cat /tmp/paperradar-seed-import.log >&2
      exit 1
    }
    cat /tmp/paperradar-seed-import.log
    imported_count="$(PGPASSWORD="$PAPERRADAR_DB_PASSWORD" psql -h "$PAPERRADAR_DB_HOST" -p "$PAPERRADAR_DB_PORT" -U "$PAPERRADAR_DB_USER" -d "$PAPERRADAR_DB_NAME" -Atc "SELECT COUNT(*) FROM papers;")"
    log "seed import complete: papers=$imported_count"
  else
    log "skipping seed import: papers table already has $paper_count rows"
  fi
else
  log "skipping seed import: PAPERRADAR_AUTO_IMPORT_SEED=$PAPERRADAR_AUTO_IMPORT_SEED seed_exists=$([ -f "$PAPERRADAR_SEED_PATH" ] && echo yes || echo no)"
fi

log "starting PaperRadar retrieval worker"
(
  cd "$PAPERRADAR_HOME/app"
  exec env PYTHONPATH=. python3 -m backend.retrieval_worker
) &
worker_pid=$!

log "starting PaperRadar API and static frontend on ${PAPERRADAR_APP_HOST}:${PAPERRADAR_APP_PORT}"
(
  cd "$PAPERRADAR_HOME/app"
  exec env PYTHONPATH=. python3 -m uvicorn backend.main:app --host "$PAPERRADAR_APP_HOST" --port "$PAPERRADAR_APP_PORT"
) &
api_pid=$!

shutdown() {
  log "shutting down"
  kill "$worker_pid" "$api_pid" 2>/dev/null || true
  runuser -u postgres -- pg_ctl -D "$PGDATA" -m fast stop >/dev/null 2>&1 || true
}
trap shutdown TERM INT

wait -n "$worker_pid" "$api_pid"
exit_code=$?
shutdown
exit "$exit_code"
