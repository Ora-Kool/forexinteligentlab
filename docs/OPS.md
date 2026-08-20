# Ops: day-to-day runbook

Research desk only — **no order placement**. Billing and team invites are deferred.

## Mac (MT5_MODE=bridge)

Requires MetaTrader 5.app logged into FBS, then one command:

```bash
cd /Users/orakool/Documents/Projects/TradingBots/forexinteligentlab
./scripts/lab.sh start     # MT5 → rpyc :18813 → FastAPI :8088
./scripts/lab.sh status
./scripts/lab.sh stop      # leaves MetaTrader open
```

From any directory:

```bash
/Users/orakool/Documents/Projects/TradingBots/forexinteligentlab/scripts/lab.sh status
```

Inside `scripts/`, use `./lab.sh status` (zsh does not search `.` without `./`).

Desk UI: [http://forextradingai.test](http://forextradingai.test) (Laravel Herd).  
API docs: [http://127.0.0.1:8088/docs](http://127.0.0.1:8088/docs)  
Logs: `.run/logs/`

First-time Wine bridge: see [MT5_MAC_BRIDGE.md](./MT5_MAC_BRIDGE.md).

### What Settings “broker label” means

The desk form stores **login id + server name only**. It does not connect MT5.
Live candles come from FastAPI (`MT5_MODE=bridge`) talking to MetaTrader via rpyc.
Use **Sync from live terminal** on Settings to copy the connected account into the workspace label.

## Windows (MT5_MODE=official)

On a Windows host with MetaTrader 5 installed and logged in:

1. Install Python deps: `pip install -r backend/requirements.txt` (includes MetaTrader5).
2. In `.env`:

```env
MT5_MODE=official
MT5_LOGIN=...
MT5_PASSWORD=...
MT5_SERVER=FBS-Demo
# optional if initialize needs it:
MT5_TERMINAL_PATH=C:\Program Files\MetaTrader 5\terminal64.exe
```

3. Start backend:

```bash
./scripts/run_backend.sh
# or: uvicorn app.main:app --host 127.0.0.1 --port 8088
```

4. Point Laravel `PYTHON_API_URL` at that host if the desk is remote.

`OfficialMT5Connector` is unchanged by the Mac bridge path. Do not set `MT5_MODE=bridge` on Windows.

## Agent mode (optional)

`MT5_MODE=agent` — FastAPI does not talk to MT5 locally; a Windows agent posts candles to `/api/agent/ingest`. Use when the desk cannot reach the terminal machine.

## Research loop

1. `./scripts/lab.sh start` (Mac) or official backend (Windows)
2. Settings → Discover → enable majors (or “Enable research majors”)
3. Auto-backfill fills `SEED_HISTORY_DAYS` (default 30) for thin instruments
4. Models → Train → Predictions (Entry / Exit / Δ) → Backtest

Training a timeframe the collector never polled (H1, H4, D1) imports its history
on demand first, so no manual import step is needed. The window widens with the
timeframe — 30 days of H4 is only ~130 bars, below the trainer's 80-labeled-bar
floor — so the first H4/D1 train takes a few extra seconds. The collector still
only polls the timeframes you enable in the monitor, so enable H4 there if you
want fresh H4 predictions to keep arriving after training. Enabling a pair in any
workspace is enough — the collector polls the union across workspaces and scores
each owner's model separately.

## Broker server clock

MetaTrader reports bar times on the *broker server* clock, not UTC. FBS runs
EET/EEST, so bars arrive +2h (winter) or +3h (summer) ahead. The adapter detects
the offset from a live tick on connect and converts to real UTC; look for
`mt5_server_offset_detected` in `.run/logs/backend.log` to confirm.

Auto-detection needs a live tick, so if you start the stack while the market is
closed the offset cannot be measured and falls back to zero. Pin it instead:

```bash
MT5_SERVER_UTC_OFFSET_MINUTES=180   # FBS summer (EEST); use 120 in winter
```

Getting this wrong shifts `hour_of_day` and the session flags, which silently
mislabels the features your models train on.

## Health checks

```bash
./scripts/lab.sh status
./scripts/mt5_mac_bridge.sh doctor   # Mac only
./scripts/mt5_mac_bridge.sh smoke
curl -s http://127.0.0.1:8088/api/health
```
