#!/usr/bin/env bash
# Helper for the macOS Wine MT5 bridge path (MT5_MODE=bridge).
# Does not change Windows official / agent setups.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

usage() {
  cat <<'EOF'
usage: ./scripts/mt5_mac_bridge.sh <command>

Commands:
  install-client   pip install backend/requirements-bridge.txt into .venv
  provision        inject Windows Python + MetaTrader5 + rpyc into MT5.app Wine
  serve            start the rpyc bridge on :18813 (keep running)
  verify           check Wine-side MetaTrader5 import
  smoke            call account_info / copy_rates via mt5-mac-bridge from macOS
  doctor           diagnose every hop and say exactly what to fix
  status           print what to run next

Typical first-time flow:
  1. Open MetaTrader 5.app and log into FBS
  2. ./scripts/mt5_mac_bridge.sh provision
  3. ./scripts/mt5_mac_bridge.sh install-client
  4. ./scripts/mt5_mac_bridge.sh serve          # leave this terminal open
  5. Set MT5_MODE=bridge in .env, restart FastAPI
  6. ./scripts/mt5_mac_bridge.sh smoke

If smoke fails, run `doctor` first -- it separates a bridge problem from a
MetaTrader login problem.
EOF
}

ensure_venv() {
  if [[ ! -d .venv ]]; then
    python3 -m venv .venv
  fi
  # shellcheck disable=SC1091
  source .venv/bin/activate
}

# Export MT5_* from .env so the bridge can authenticate the account, without
# overriding anything already set in the caller's shell.
load_env() {
  [[ -f .env ]] || return 0
  while IFS='=' read -r key value; do
    [[ "$key" == MT5_* ]] || continue
    value="${value%\"}"; value="${value#\"}"
    if [[ -z "${!key:-}" ]]; then
      export "$key=$value"
    fi
  done < <(grep -E '^MT5_[A-Z_]+=' .env || true)
}

cmd="${1:-}"
case "$cmd" in
  install-client)
    ensure_venv
    pip install -r backend/requirements-bridge.txt
    python -c "import mt5_mac_bridge; print('mt5-mac-bridge OK')"
    ;;
  provision|serve|verify)
    exec "$ROOT/scripts/mt5_native_bridge.sh" "$cmd"
    ;;
  smoke)
    ensure_venv
    load_env
    export MT5_BACKEND=bridge
    export MT5_BRIDGE_HOST="${MT5_BRIDGE_HOST:-127.0.0.1}"
    export MT5_BRIDGE_PORT="${MT5_BRIDGE_PORT:-18813}"
    if ! python "$ROOT/scripts/mt5_bridge_smoke.py"; then
      echo
      echo "smoke failed -- running doctor to locate the broken hop:"
      python "$ROOT/scripts/mt5_bridge_doctor.py"
      exit 1
    fi
    ;;
  doctor)
    ensure_venv
    exec python "$ROOT/scripts/mt5_bridge_doctor.py"
    ;;
  status)
    cat <<EOF
MT5.app:        /Applications/MetaTrader 5.app
Wine prefix:    \$HOME/Library/Application Support/net.metaquotes.wine.metatrader5
Bridge port:    ${MT5_BRIDGE_PORT:-18813}
Backend mode:   set MT5_MODE=bridge in .env (leave official for Windows)

Windows path is unchanged: MT5_MODE=official uses OfficialMT5Connector as before.
EOF
    ;;
  *)
    usage
    exit 1
    ;;
esac
