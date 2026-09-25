#!/usr/bin/env bash
# Install, build, seed, start, run one Playwright spec (or all), then stop.
# Workers call this once. They do not install, build, or launch a browser themselves.
set -u

cd "$(dirname "$0")/.."
PROJECT_ROOT="$(cd .. && pwd)"
ARC_DIR="${PROJECT_ROOT}/.arc"
mkdir -p "$ARC_DIR"

SPEC="${1:-}"
if [ -f "${ARC_DIR}/port" ]; then
  PORT="$(tr -d '[:space:]' < "${ARC_DIR}/port")"
fi
PORT="${PORT:-3000}"
export PORT
export PLAYWRIGHT_BASE_URL="http://127.0.0.1:${PORT}"
LOCK="${ARC_DIR}/e2e.lock"
LOG="${ARC_DIR}/pw.log"
SERVER_LOG="${ARC_DIR}/server.log"
PID_FILE="${ARC_DIR}/server.pid"
NPM_BACKEND_LOG="${ARC_DIR}/npm-backend.log"
NPM_FRONTEND_LOG="${ARC_DIR}/npm-frontend.log"
BUILD_LOG="${ARC_DIR}/frontend-build.log"
SEED_LOG="${ARC_DIR}/seed.log"
PW_INSTALL_LOG="${ARC_DIR}/pw-install.log"

if [ -n "$SPEC" ] && ! printf '%s' "$SPEC" | grep -Eq '^REQ-[0-9.]+$'; then
  echo "bad spec id: $SPEC"
  exit 2
fi

stop_server() {
  if [ -f "$PID_FILE" ]; then
    pid=$(cat "$PID_FILE" 2>/dev/null || true)
    if [ -n "${pid:-}" ]; then
      kill "$pid" 2>/dev/null || true
    fi
    rm -f "$PID_FILE"
  fi
  if command -v lsof >/dev/null 2>&1; then
    pids=$(lsof -ti "tcp:${PORT}" 2>/dev/null || true)
    if [ -n "${pids:-}" ]; then
      # shellcheck disable=SC2086
      kill $pids 2>/dev/null || true
    fi
  fi
}

release_lock() {
  rm -rf "$LOCK"
}

trap 'release_lock; stop_server' EXIT

if ! mkdir "$LOCK" 2>/dev/null; then
  old=$(cat "$LOCK/pid" 2>/dev/null || true)
  if [ -n "${old:-}" ]; then
    echo "waiting for other spec pid $old"
    i=0
    while [ "$i" -lt 180 ]; do
      kill -0 "$old" 2>/dev/null || break
      i=$((i + 1))
      sleep 1
    done
  fi
  rm -rf "$LOCK"
  mkdir "$LOCK"
fi
echo $$ > "$LOCK/pid"

ulimit -c 0 || true

if [ ! -d node_modules ]; then
  echo "installing backend dependencies"
  npm install --no-audit --no-fund > "$NPM_BACKEND_LOG" 2>&1 || {
    tail -n 30 "$NPM_BACKEND_LOG"
    exit 1
  }
fi

front="$(cd ../frontend && pwd)"
if [ ! -d "$front/node_modules" ]; then
  echo "installing frontend dependencies"
  (cd "$front" && npm install --no-audit --no-fund > "$NPM_FRONTEND_LOG" 2>&1) || {
    tail -n 30 "$NPM_FRONTEND_LOG"
    exit 1
  }
fi

need_build=0
if [ ! -f "$front/dist/index.html" ]; then
  need_build=1
elif [ -n "$(find "$front/src" -type f -newer "$front/dist/index.html" -print -quit 2>/dev/null)" ]; then
  need_build=1
fi
if [ "$need_build" = 1 ]; then
  echo "building frontend"
  (cd "$front" && npm run build > "$BUILD_LOG" 2>&1) || {
    tail -n 40 "$BUILD_LOG"
    exit 1
  }
fi

if [ -f src/database/seed_db.js ]; then
  npm run db:seed > "$SEED_LOG" 2>&1 || {
    tail -n 30 "$SEED_LOG"
    exit 1
  }
fi

if [ -n "$SPEC" ] && [ ! -f "test-e2e/${SPEC}.spec.js" ]; then
  echo "missing test-e2e/${SPEC}.spec.js"
  exit 2
fi

stop_server
sleep 0.5

start_server() {
  if command -v setsid >/dev/null 2>&1; then
    setsid nohup node src/index.js > "$SERVER_LOG" 2>&1 < /dev/null &
    echo $! > "$PID_FILE"
  else
    python3 - "$SERVER_LOG" "$PID_FILE" << 'PY'
import subprocess, sys
log, pid_file = sys.argv[1], sys.argv[2]
handle = open(log, "w")
proc = subprocess.Popen(
    ["node", "src/index.js"],
    stdout=handle,
    stderr=subprocess.STDOUT,
    stdin=subprocess.DEVNULL,
    start_new_session=True,
)
open(pid_file, "w").write(str(proc.pid))
PY
  fi
}

start_server

ready=0
i=0
while [ "$i" -lt 40 ]; do
  if curl -sf -m 1 "$PLAYWRIGHT_BASE_URL/api/health" >/dev/null 2>&1; then
    ready=1
    break
  fi
  i=$((i + 1))
  sleep 0.5
done
if [ "$ready" != 1 ]; then
  echo "server failed to start"
  tail -n 40 "$SERVER_LOG" 2>/dev/null || true
  exit 1
fi

run_browser() {
  browser="$1"
  if [ -n "$SPEC" ]; then
    npx playwright test "test-e2e/${SPEC}.spec.js" --browser="$browser" --reporter=line > "$LOG" 2>&1
  else
    npx playwright test --browser="$browser" --reporter=line > "$LOG" 2>&1
  fi
}

crashed() {
  grep -E -q 'SIGTRAP|SIGSEGV|SIGABRT' "$LOG"
}

run_browser chromium
status=$?
if [ "$status" -ne 0 ] && grep -q 'Executable doesn' "$LOG"; then
  echo "installing chromium"
  npx playwright install chromium > "$PW_INSTALL_LOG" 2>&1 || tail -n 20 "$PW_INSTALL_LOG"
  run_browser chromium
  status=$?
fi
if [ "$status" -ne 0 ] && crashed; then
  echo "chromium crashed, retrying firefox once"
  run_browser firefox
  status=$?
fi

echo "playwright exit ${status}"
tail -n 60 "$LOG" 2>/dev/null || true
exit "$status"
