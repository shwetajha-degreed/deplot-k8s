#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
API_ONLY=false
E2E_ONLY=false
START_SERVERS=false
INSTALL=false

while [[ $# -gt 0 ]]; do
  case "$1" in
    --api-only) API_ONLY=true ;;
    --e2e-only) E2E_ONLY=true ;;
    --start-servers) START_SERVERS=true ;;
    --install) INSTALL=true ;;
    *) echo "Unknown option: $1"; exit 1 ;;
  esac
  shift
done

wait_url() {
  local url=$1 max=${2:-90} i=0
  while [[ $i -lt $max ]]; do
    if curl -sf "$url" >/dev/null 2>&1; then return 0; fi
    sleep 2
    i=$((i + 2))
  done
  return 1
}

if $INSTALL; then
  pip install -e "$ROOT/backend[dev]" -q
  (cd "$ROOT/frontend" && npm install && npx playwright install chromium)
fi

BACKEND_PID=""
FRONTEND_PID=""
cleanup() {
  [[ -n "$BACKEND_PID" ]] && kill "$BACKEND_PID" 2>/dev/null || true
  [[ -n "$FRONTEND_PID" ]] && kill "$FRONTEND_PID" 2>/dev/null || true
}
trap cleanup EXIT

if $START_SERVERS; then
  (cd "$ROOT/backend" && python -m uvicorn app.main:app --host 127.0.0.1 --port 8000) &
  BACKEND_PID=$!
  wait_url "http://localhost:8000/api/v1/health"

  (cd "$ROOT/frontend" && NEXT_PUBLIC_API_URL=http://localhost:8000/api/v1 npm run dev -- --port 3000) &
  FRONTEND_PID=$!
  wait_url "http://localhost:3000"
fi

EXIT=0

if ! $E2E_ONLY; then
  echo "=== API regression (pytest) ==="
  (cd "$ROOT/backend" && python -m pytest tests/ -v --tb=short) || EXIT=1
fi

if ! $API_ONLY; then
  echo "=== Web regression (Playwright) ==="
  (cd "$ROOT/frontend" && PLAYWRIGHT_SKIP_WEBSERVER=1 npx playwright test) || EXIT=1
fi

exit $EXIT
