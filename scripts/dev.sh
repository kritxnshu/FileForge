#!/usr/bin/env bash
# Native dev stack: Redis, FastAPI, two arq workers, Next.js, Caddy. Open http://localhost:8080
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
API="$ROOT/services/api"
PY="$API/.venv/bin/python"
export STORAGE_DIR="${STORAGE_DIR:-$ROOT/.data/storage}"
export REDIS_URL="${REDIS_URL:-redis://127.0.0.1:6379/0}"
export TRUSTED_PROXY_HOPS="${TRUSTED_PROXY_HOPS:-1}"
export COOKIE_SECURE="${COOKIE_SECURE:-true}"   # browsers accept Secure cookies on http://localhost
export INTERNAL_API_URL="${INTERNAL_API_URL:-http://127.0.0.1:8000}"
WEB_MODE="${WEB_MODE:-dev}"   # dev | start (production build)
mkdir -p "$STORAGE_DIR" "$ROOT/.data/logs"
LOGS="$ROOT/.data/logs"

pids=()
cleanup() { for p in "${pids[@]}"; do kill "$p" 2>/dev/null || true; done; wait 2>/dev/null || true; }
trap cleanup EXIT INT TERM

if ! redis-cli -u "$REDIS_URL" ping >/dev/null 2>&1; then
  redis-server --port 6379 --save "" --appendonly no >"$LOGS/redis.log" 2>&1 & pids+=($!)
  sleep 0.5
fi
(cd "$API" && exec "$PY" -m uvicorn app.main:app --host 127.0.0.1 --port 8000 --proxy-headers) >"$LOGS/api.log" 2>&1 & pids+=($!)
(cd "$API" && exec "$PY" -m arq worker.FastWorker) >"$LOGS/worker-fast.log" 2>&1 & pids+=($!)
(cd "$API" && exec "$PY" -m arq worker.HeavyWorker) >"$LOGS/worker-heavy.log" 2>&1 & pids+=($!)
if [ "$WEB_MODE" = "start" ]; then
  (cd "$ROOT/apps/web" && exec pnpm start -p 3000 -H 127.0.0.1) >"$LOGS/web.log" 2>&1 & pids+=($!)
else
  (cd "$ROOT/apps/web" && exec pnpm dev -p 3000 -H 127.0.0.1) >"$LOGS/web.log" 2>&1 & pids+=($!)
fi
caddy run --config "$ROOT/deploy/Caddyfile" --adapter caddyfile >"$LOGS/caddy.log" 2>&1 & pids+=($!)
echo "Universal Converter: http://localhost:8080   (logs in .data/logs)"
wait
