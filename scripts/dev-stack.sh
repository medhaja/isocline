#!/usr/bin/env bash
# Lightweight stack WITHOUT Docker, for development and E2E tests:
# SQLite, runs executed inside the API process (ISOCLINE_INLINE_WORKER), sandbox in process mode.
# NOT for production: no crash recovery, no horizontal scaling, and process-mode Python is not isolated.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
DB="${E2E_DB:-/tmp/isocline-dev.db}"
export ISOCLINE_DATABASE_URL="sqlite+aiosqlite:///$DB" ISOCLINE_INLINE_WORKER=true ISOCLINE_STORAGE_LOCAL_PATH=/tmp/isocline-uploads \
  ISOCLINE_REDIS_URL="${ISOCLINE_REDIS_URL:-redis://127.0.0.1:6399/0}" ISOCLINE_SANDBOX_URL=http://127.0.0.1:8100 ISOCLINE_SANDBOX_TOKEN=dev-sandbox-token \
  ISOCLINE_WORKSPACE_ROOT="${ISOCLINE_WORKSPACE_ROOT:-/tmp/isocline-workspaces}" NEXT_TELEMETRY_DISABLED=1
[ "${E2E_RESET:-1}" = "1" ] && rm -f "$DB"
(cd "$ROOT/apps/api" && alembic upgrade head)
(cd "$ROOT/apps/api" && exec uvicorn isocline.main:app --port 8000) &
(cd "$ROOT/workers/python-sandbox" && SANDBOX_TOKEN=dev-sandbox-token SANDBOX_MODE=process SANDBOX_ALLOW_UNSAFE_PROCESS=true exec uvicorn app:app --port 8100) &
(cd "$ROOT/apps/web" && { [ -d .next ] || npm run build; } && exec npx next start -p 3000) &
# E2E fixture site for browser automation (local, so tests never touch the internet)
(cd "$ROOT/tests/e2e/fixtures/site" && exec python3 -m http.server 8765 --bind 127.0.0.1) &
trap 'kill $(jobs -p) 2>/dev/null' EXIT
wait
