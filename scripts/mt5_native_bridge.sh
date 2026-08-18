#!/usr/bin/env bash
# Provision / serve an rpyc bridge inside MetaTrader 5.app's Wine prefix.
# Official Windows adapters are unaffected — this is macOS-only.
#
# Subcommands: provision | serve | verify
set -euo pipefail

APP="/Applications/MetaTrader 5.app"
WINE="$APP/Contents/SharedSupport/wine/bin/wine"
export WINEPREFIX="${WINEPREFIX:-$HOME/Library/Application Support/net.metaquotes.wine.metatrader5}"
export WINEDEBUG="${WINEDEBUG:--all}"
export WINEDLLOVERRIDES="mscoree=d;mshtml=d"
PORT="${MT5_NATIVE_PORT:-${MT5_BRIDGE_PORT:-18813}}"
PYDIR_WIN='C:\Python311'
PYEXE="$WINEPREFIX/drive_c/Python311/python.exe"
PYVER="3.11.9"

if [[ ! -x "$WINE" ]]; then
  echo "MetaTrader 5.app wine not found at: $WINE"
  echo "Install MetaTrader 5 for macOS first, then launch it once."
  exit 1
fi

provision() {
  mkdir -p "$WINEPREFIX/drive_c"
  cd "$WINEPREFIX/drive_c"

  if [[ ! -f "$PYEXE" ]]; then
    echo "[1/3] Installing embeddable Python $PYVER into Wine prefix…"
    curl -fsSL -o /tmp/py-embed-mt5.zip "https://www.python.org/ftp/python/${PYVER}/python-${PYVER}-embed-amd64.zip"
    /usr/bin/python3 -m zipfile -e /tmp/py-embed-mt5.zip "$WINEPREFIX/drive_c/Python311/"
    printf 'python311.zip\n.\nimport site\n' > "$WINEPREFIX/drive_c/Python311/python311._pth"
  else
    echo "[1/3] Python already present at $PYEXE"
  fi

  echo "[2/3] Bootstrapping pip under app Wine (first run is slow)…"
  curl -fsSL -o "$WINEPREFIX/drive_c/get-pip.py" https://bootstrap.pypa.io/get-pip.py
  "$WINE" "$PYDIR_WIN\\python.exe" 'C:\get-pip.py' --no-warn-script-location || true

  echo "[3/3] Installing MetaTrader5 + rpyc + numpy<2 inside Wine…"
  "$WINE" "$PYDIR_WIN\\python.exe" -m pip install --no-cache-dir --no-warn-script-location \
    "MetaTrader5" "rpyc==6.0.2" "numpy<2"

  verify
  echo
  echo "Provision complete. Next:"
  echo "  1. Open MetaTrader 5.app and log into your FBS account"
  echo "  2. ./scripts/mt5_native_bridge.sh serve"
  echo "  3. Set MT5_MODE=bridge in .env and restart the backend"
}

verify() {
  echo "verify: importing MetaTrader5 under app Wine…"
  "$WINE" "$PYDIR_WIN\\python.exe" -c \
    "import MetaTrader5 as mt5, rpyc, numpy; print('OK | MetaTrader5', getattr(mt5,'__version__','?'), '| rpyc', rpyc.__version__, '| numpy', numpy.__version__)"
}

serve() {
  if [[ ! -f "$PYEXE" ]]; then
    echo "Wine Python missing. Run: ./scripts/mt5_native_bridge.sh provision"
    exit 1
  fi
  echo "Starting rpyc SlaveService on 0.0.0.0:${PORT} via MetaTrader 5.app Wine."
  echo "Keep MetaTrader 5.app open and logged into FBS. Ctrl+C to stop."
  exec "$WINE" "$PYDIR_WIN\\python.exe" -c \
    "from rpyc.utils.server import ThreadedServer; from rpyc.core import SlaveService; ThreadedServer(SlaveService, hostname='0.0.0.0', port=${PORT}, reuse_addr=True, protocol_config={'allow_all_attrs':True,'allow_public_attrs':True}).start()"
}

case "${1:-}" in
  provision) provision ;;
  serve) serve ;;
  verify) verify ;;
  *)
    echo "usage: $0 {provision|serve|verify}"
    exit 1
    ;;
esac
