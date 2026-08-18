# Mac Wine bridge (MT5_MODE=bridge)

Use this only on macOS with MetaTrader 5.app. Windows hosts keep using
`MT5_MODE=official` or `MT5_MODE=agent` — those adapters are unchanged.

## Architecture

```text
FBS account
  → MetaTrader 5.app (Wine)
  → Windows Python + MetaTrader5 + rpyc   (scripts/mt5_native_bridge.sh serve)
  → localhost:18813
  → mt5-mac-bridge (macOS Python)
  → BridgeMT5Connector  (wraps OfficialMT5Connector, does not edit it)
  → FastAPI collector / dashboard
```

## One-time setup

1. Open **MetaTrader 5.app** and log into your FBS demo/live account. Leave it open.
2. From the repo root:

```bash
./scripts/mt5_mac_bridge.sh provision
./scripts/mt5_mac_bridge.sh install-client
```

3. Start the bridge (keep this terminal running):

```bash
./scripts/mt5_mac_bridge.sh serve
```

4. In `.env`:

```env
MT5_MODE=bridge
MT5_BRIDGE_HOST=127.0.0.1
MT5_BRIDGE_PORT=18813
MT5_LOGIN=your_fbs_login
MT5_PASSWORD=your_mt5_password
MT5_SERVER=FBS-Demo
# Optional Wine-side path if initialize needs it:
MT5_TERMINAL_PATH=C:\Program Files\MetaTrader 5\terminal64.exe
```

5. Restart FastAPI, then:

```bash
./scripts/mt5_mac_bridge.sh smoke
```

6. In the desk: Settings → Discover symbols → enable instruments → Start collector.

## Day-to-day

See **[OPS.md](./OPS.md)** for the full Mac + Windows runbook.

One command starts everything in the required order:

```bash
./scripts/lab.sh start    # MetaTrader → rpyc bridge → FastAPI
./scripts/lab.sh status   # which adapter + health
./scripts/lab.sh stop     # stops bridge + FastAPI (leaves MT5 open)
```

Start order matters:

1. **MetaTrader 5.app** — opened automatically if needed; you must stay logged into FBS
2. **rpyc bridge** (`:18813`) — Wine-side Python talking to the terminal
3. **FastAPI** (`:8088`) — collector starts on boot when `MT5_MODE=bridge`

On collector start, **auto-backfill** pulls `SEED_HISTORY_DAYS` of M5 history for any
monitored instrument that is still thin (default on via `AUTO_BACKFILL=true`).
Live polling continues after that. Re-runs are safe — duplicates are skipped.

Laravel/Herd (`http://forextradingai.test`) is separate and usually already running.

Logs land in `.run/logs/`.

## Safety

- Research / market data only. Orders stay disabled.
- Balance is still hidden in the API status payload.
- For live execution later, prefer native Windows (`MT5_MODE=official`), not Wine.

## Troubleshooting

Start with the doctor — it checks each hop separately and tells you which one is
broken, so a MetaTrader login problem is not mistaken for a bridge problem:

```bash
./scripts/mt5_mac_bridge.sh doctor
```

It reports the Wine prefix, terminal build, trade servers the terminal has
actually connected to, the terminal's own authorization log lines, the rpyc
port, and the result of `initialize()`.

| Symptom | Fix |
|---|---|
| `Could not reach the Wine MT5 rpyc bridge` | Run `serve`; confirm port 18813 is listening |
| `-6 Terminal: Authorization failed` | The terminal has no authorized account. See below. |
| `-10005 IPC timeout` | Log into FBS in the MT5 GUI first |
| `mt5-mac-bridge is not installed` | `./scripts/mt5_mac_bridge.sh install-client` |
| Symbol missing | Use exact Market Watch names from Discover |
| Want Windows again | Set `MT5_MODE=official` — OfficialMT5Connector is untouched |

### `-6 Terminal: Authorization failed`

The bridge is fine; the terminal is not logged into a trade account. The Python
API cannot attach until the terminal itself has authorized once.

MetaTrader 5 for macOS ships as the generic MetaQuotes build, so FBS is **not**
in its broker list until you add it. Entering an FBS login while the dialog
still points at `MetaQuotes-Demo` logs `authorization on MetaQuotes-Demo failed
(Invalid account)` and leaves the terminal unauthorized.

In the MetaTrader 5 window:

1. `File > Open an Account`.
2. Search for `FBS Markets Inc.` and select it.
3. Choose **Connect with an existing trade account**.
4. Enter your login, password, and pick the `FBS-Demo` server (live accounts use
   `FBS-Real-<n>`; the exact server is shown in the FBS Trader Area under
   Account Info).
5. Wait for the status bar bottom-right to show a live ping instead of
   `No connection`.

`doctor` then lists `FBS-Demo` under connected trade servers, and `smoke` works.

If `FBS Markets Inc.` does not appear in the search, install the FBS-branded
terminal into the same Wine prefix so its servers are registered:

```bash
WINEPREFIX="$HOME/Library/Application Support/net.metaquotes.wine.metatrader5" \
  "/Applications/MetaTrader 5.app/Contents/SharedSupport/wine/bin/wine" ~/Downloads/fbs5setup.exe
```
