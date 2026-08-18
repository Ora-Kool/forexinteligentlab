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

## Health checks

```bash
./scripts/lab.sh status
./scripts/mt5_mac_bridge.sh doctor   # Mac only
./scripts/mt5_mac_bridge.sh smoke
curl -s http://127.0.0.1:8088/api/health
```
