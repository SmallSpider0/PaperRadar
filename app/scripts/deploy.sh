#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "$0")/../.." && pwd)"
FRONTEND_DIR="$ROOT_DIR/app/frontend"
MODE="${1:-all}"

run_frontend() {
  cd "$FRONTEND_DIR"
  npm run verify
  npm run build
  rsync -a --delete out/ /var/www/paperradar/
}

run_backend() {
  systemctl restart paperradar-api
  systemctl is-active paperradar-api
  systemctl restart paperradar-retrieval-worker
  systemctl is-active paperradar-retrieval-worker
  for i in 1 2 3 4 5; do
    if curl -sS http://127.0.0.1:8100/health >/dev/null; then
      curl -sS http://127.0.0.1:8100/health
      return 0
    fi
    sleep 1
  done
  echo "Backend health check failed after retries"
  return 1
}

case "$MODE" in
  frontend)
    run_frontend
    systemctl reload nginx
    ;;
  backend)
    run_backend
    ;;
  all)
    run_frontend
    run_backend
    systemctl reload nginx
    ;;
  *)
    echo "Usage: $0 [frontend|backend|all]"
    exit 1
    ;;
esac

echo "Deploy done: mode=$MODE"
