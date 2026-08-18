#!/usr/bin/env bash
# One-command day-to-day runner for Forex Intelligence Lab on macOS (bridge mode).
#
# Correct start order:
#   1. MetaTrader 5.app  (GUI, must already be logged into FBS)
#   2. rpyc Wine bridge  (:18813)
#   3. FastAPI backend   (:8088)  — collector starts automatically
#
# Laravel/Herd stays separate (forextradingai.test). Windows adapters are untouched.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

RUN_DIR="$ROOT/.run"
LOG_DIR="$RUN_DIR/logs"
BRIDGE_PID_FILE="$RUN_DIR/bridge.pid"
BACKEND_PID_FILE="$RUN_DIR/backend.pid"
BRIDGE_LOG="$LOG_DIR/bridge.log"
BACKEND_LOG="$LOG_DIR/backend.log"
BRIDGE_PORT="${MT5_BRIDGE_PORT:-18813}"
BACKEND_PORT="${APP_PORT:-8088}"
MT5_APP="/Applications/MetaTrader 5.app"

mkdir -p "$LOG_DIR"

usage() {
  cat <<'EOF'
usage: ./scripts/lab.sh <command>

Commands:
  start     open MT5 (if needed), start bridge + FastAPI in the right order
  stop      stop FastAPI and the rpyc bridge (leaves MetaTrader open)
  restart   stop then start
  status    show what is running and which adapter is active
  smoke     quick live FBS read through the bridge

Day-to-day:
  ./scripts/lab.sh start
  open http://forextradingai.test   # Laravel/Herd desk
  ./scripts/lab.sh status
  ./scripts/lab.sh stop
EOF
}

load_env() {
  [[ -f .env ]] || return 0
  while IFS='=' read -r key value; do
    [[ "$key" =~ ^[A-Z0-9_]+$ ]] || continue
    value="${value%"${value##*[![:space:]]}"}"
    value="${value#"${value%%[![:space:]]*}"}"
    value="${value%\"}"; value="${value#\"}"
    value="${value%\'}"; value="${value#\'}"
    if [[ -z "${!key:-}" ]]; then
      export "$key=$value"
    fi
  done < <(grep -E '^[A-Z0-9_]+=' .env || true)
}

mode() {
  load_env
  echo "${MT5_MODE:-mock}" | tr '[:upper:]' '[:lower:]'
}

port_listening() {
  local port="$1"
  lsof -nP -iTCP:"$port" -sTCP:LISTEN >/dev/null 2>&1
}

pid_alive() {
  local file="$1"
  [[ -f "$file" ]] || return 1
  local pid
  pid="$(cat "$file" 2>/dev/null || true)"
  [[ -n "${pid:-}" ]] && kill -0 "$pid" 2>/dev/null
}

mt5_running() {
  pgrep -fq 'terminal64.exe' 2>/dev/null || pgrep -fq 'MetaTrader 5' 2>/dev/null
}

ensure_mt5() {
  if mt5_running; then
    echo "[ok] MetaTrader 5 is running"
    return 0
  fi
  if [[ ! -d "$MT5_APP" ]]; then
    echo "[fail] MetaTrader 5.app not found at $MT5_APP"
    exit 1
  fi
  echo "[..] Opening MetaTrader 5.app — log into FBS-Demo if the status bar shows No connection"
  open -a "$MT5_APP"
  # Wine boot is slow; wait until terminal64 appears.
  local i
  for i in $(seq 1 60); do
    if mt5_running; then
      echo "[ok] MetaTrader 5 process detected"
      echo "     Wait until the bottom-right shows a live ping, then continue if needed."
      return 0
    fi
    sleep 1
  done
  echo "[warn] MetaTrader 5 did not show terminal64.exe yet — keep the window open and logged in"
}

start_bridge() {
  if port_listening "$BRIDGE_PORT"; then
    echo "[ok] bridge already listening on :$BRIDGE_PORT"
    return 0
  fi
  echo "[..] starting Wine rpyc bridge on :$BRIDGE_PORT"
  # Own session, so closing this terminal cannot take the bridge down with it.
  python3 "$ROOT/scripts/spawn_detached.py" "$BRIDGE_LOG" "$BRIDGE_PID_FILE" \
    "$ROOT/scripts/mt5_native_bridge.sh" serve
  local i
  for i in $(seq 1 30); do
    if port_listening "$BRIDGE_PORT"; then
      echo "[ok] bridge up (pid $(cat "$BRIDGE_PID_FILE"))"
      return 0
    fi
    sleep 1
  done
  echo "[fail] bridge did not open :$BRIDGE_PORT — see $BRIDGE_LOG"
  tail -20 "$BRIDGE_LOG" || true
  exit 1
}

start_backend() {
  if port_listening "$BACKEND_PORT"; then
    echo "[ok] FastAPI already listening on :$BACKEND_PORT"
    return 0
  fi
  if [[ ! -d .venv ]]; then
    python3 -m venv .venv
  fi
  # shellcheck disable=SC1091
  source .venv/bin/activate
  pip install -q -r backend/requirements.txt
  if [[ "$(mode)" == "bridge" ]]; then
    pip install -q -r backend/requirements-bridge.txt
  fi
  echo "[..] starting FastAPI on :$BACKEND_PORT (MT5_MODE=$(mode))"
  python3 "$ROOT/scripts/spawn_detached.py" "$BACKEND_LOG" "$BACKEND_PID_FILE" \
    env "PYTHONPATH=$ROOT/backend" \
    "$ROOT/.venv/bin/uvicorn" app.main:app \
    --app-dir "$ROOT/backend" --host 127.0.0.1 --port "$BACKEND_PORT"
  local i
  for i in $(seq 1 45); do
    if curl -sf "http://127.0.0.1:${BACKEND_PORT}/api/health" >/dev/null 2>&1; then
      echo "[ok] FastAPI up (pid $(cat "$BACKEND_PID_FILE"))"
      return 0
    fi
    if pid_alive "$BACKEND_PID_FILE"; then
      :
    elif [[ $i -gt 5 ]]; then
      echo "[fail] FastAPI exited early — see $BACKEND_LOG"
      tail -40 "$BACKEND_LOG" || true
      exit 1
    fi
    sleep 1
  done
  echo "[fail] FastAPI health check timed out — see $BACKEND_LOG"
  tail -40 "$BACKEND_LOG" || true
  exit 1
}

stop_pid_file() {
  local name="$1"
  local file="$2"
  if ! pid_alive "$file"; then
    rm -f "$file"
    return 0
  fi
  local pid
  pid="$(cat "$file")"
  echo "[..] stopping $name (pid $pid)"
  # Detached services are session leaders, so the negative pid stops the group.
  kill -TERM -"$pid" 2>/dev/null || kill -TERM "$pid" 2>/dev/null || true
  local i
  for i in $(seq 1 10); do
    kill -0 "$pid" 2>/dev/null || break
    sleep 0.3
  done
  kill -9 -"$pid" 2>/dev/null || kill -9 "$pid" 2>/dev/null || true
  rm -f "$file"
}

stop_port_owners() {
  local port="$1"
  local pids
  pids="$(lsof -tiTCP:"$port" -sTCP:LISTEN 2>/dev/null || true)"
  if [[ -z "${pids}" ]]; then
    return 0
  fi
  # shellcheck disable=SC2086
  kill $pids 2>/dev/null || true
  sleep 0.5
  pids="$(lsof -tiTCP:"$port" -sTCP:LISTEN 2>/dev/null || true)"
  if [[ -n "${pids}" ]]; then
    # shellcheck disable=SC2086
    kill -9 $pids 2>/dev/null || true
  fi
}

stop_all() {
  stop_pid_file "FastAPI" "$BACKEND_PID_FILE"
  stop_port_owners "$BACKEND_PORT"
  # Bridge runs under Wine; killing the wrapper may leave wineserver holding the port.
  stop_pid_file "bridge wrapper" "$BRIDGE_PID_FILE"
  # Best-effort: stop Wine python that hosts ThreadedServer on the bridge port.
  pkill -f "ThreadedServer\\(SlaveService" 2>/dev/null || true
  sleep 1
  if port_listening "$BRIDGE_PORT"; then
    echo "[warn] :$BRIDGE_PORT still listening (often via wineserver). Retrying..."
    stop_port_owners "$BRIDGE_PORT"
  fi
  echo "[ok] lab processes stopped (MetaTrader 5 left running)"
}

print_status() {
  load_env
  local m
  m="$(mode)"
  echo "MT5_MODE=$m"
  if mt5_running; then echo "MT5.app:     running"; else echo "MT5.app:     stopped"; fi
  if port_listening "$BRIDGE_PORT"; then echo "bridge:      listening :$BRIDGE_PORT"; else echo "bridge:      down"; fi
  if port_listening "$BACKEND_PORT"; then echo "FastAPI:     listening :$BACKEND_PORT"; else echo "FastAPI:     down"; fi

  if port_listening "$BACKEND_PORT"; then
    echo
    curl -sf "http://127.0.0.1:${BACKEND_PORT}/api/health" | python3 -m json.tool 2>/dev/null || echo "(health unavailable)"
  fi
  echo
  echo "desk:  http://forextradingai.test"
  echo "api:   http://127.0.0.1:${BACKEND_PORT}/docs"
  echo "logs:  $LOG_DIR/"
}

start_all() {
  load_env
  local m
  m="$(mode)"
  echo "Starting lab (MT5_MODE=$m)"
  echo "Order: MetaTrader → bridge → FastAPI"
  echo

  case "$m" in
    bridge)
      ensure_mt5
      start_bridge
      # Brief settle so Wine IPC is ready before backend initialize().
      sleep 2
      start_backend
      echo
      echo "[..] smoke check"
      if "$ROOT/scripts/mt5_mac_bridge.sh" smoke >/tmp/fil-lab-smoke.out 2>&1; then
        tail -5 /tmp/fil-lab-smoke.out
        echo "[ok] live FBS bridge read succeeded"
      else
        echo "[warn] smoke failed — run: ./scripts/mt5_mac_bridge.sh doctor"
        tail -20 /tmp/fil-lab-smoke.out || true
      fi
      ;;
    mock|agent|official)
      echo "[info] bridge steps skipped for MT5_MODE=$m"
      start_backend
      ;;
    *)
      echo "[fail] unknown MT5_MODE=$m"
      exit 1
      ;;
  esac

  echo
  print_status
}

cmd="${1:-}"
case "$cmd" in
  start) start_all ;;
  stop) stop_all ;;
  restart) stop_all; sleep 1; start_all ;;
  status) print_status ;;
  smoke) exec "$ROOT/scripts/mt5_mac_bridge.sh" smoke ;;
  *) usage; exit 1 ;;
esac
