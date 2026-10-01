#!/bin/bash
# Start/stop API, Celery worker, beat and the Python sandbox as local processes (CI and development without Docker).
#   scripts/ci_stack.sh start|stop|restart <api|worker|beat|sandbox|all>
# Uses the current environment (ISOCLINE_* variables). PIDs and logs go to ${STACK_DIR:-/tmp/isocline-stack}.
set -u
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
D="${STACK_DIR:-/tmp/isocline-stack}"; mkdir -p "$D"
start() {
  if [ -f "$D/$1.pid" ] && kill -0 "$(cat "$D/$1.pid")" 2>/dev/null; then
    echo "$1 is already running (pid $(cat "$D/$1.pid")); stop it first" >&2; return 0
  fi
  # Each service writes its own PID from inside the new session (`echo $$` then `exec`), so the PID file always names
  # the real process-group leader. (`$!` would name `setsid`, which forks when called from a group leader.)
  local cmd dir
  case $1 in
    api) dir="$ROOT/apps/api"; cmd="uvicorn isocline.main:app --host 127.0.0.1 --port 8000" ;;
    worker) dir="$ROOT/apps/api"; cmd="celery -A isocline.worker.celery_app worker -Q runs,ingest,maintenance --concurrency ${WORKER_CONCURRENCY:-2} --loglevel INFO -n w$RANDOM@%h" ;;
    beat) dir="$ROOT/apps/api"; cmd="celery -A isocline.worker.celery_app beat --loglevel INFO --schedule $D/beat-schedule" ;;
    sandbox) dir="$ROOT/workers/python-sandbox"; cmd="env SANDBOX_TOKEN=${ISOCLINE_SANDBOX_TOKEN:-} uvicorn app:app --host 127.0.0.1 --port 8100" ;;
    *) echo "unknown service $1" >&2; return 1 ;;
  esac
  rm -f "$D/$1.pid"
  (cd "$dir" && setsid bash -c "echo \$\$ > '$D/$1.pid'; exec $cmd" >>"$D/$1.log" 2>&1 </dev/null &)
  for _ in 1 2 3 4 5 6 7 8 9 10; do [ -s "$D/$1.pid" ] && break; sleep 0.2; done
}
stop() { [ -f "$D/$1.pid" ] && { kill -"${SIG:-TERM}" -- -"$(cat "$D/$1.pid")" 2>/dev/null || kill -"${SIG:-TERM}" "$(cat "$D/$1.pid")" 2>/dev/null; rm -f "$D/$1.pid"; }; return 0; }
svcs="$2"; [ "$svcs" = all ] && svcs="api worker beat sandbox"
for s in $svcs; do case $1 in start) start "$s";; stop) stop "$s";; restart) stop "$s"; sleep 2; start "$s";; esac; done
