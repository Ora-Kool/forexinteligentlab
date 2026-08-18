# Forex Intelligence Lab

Research desk for collecting FBS / MetaTrader 5 market data, computing features, training models, and reviewing **research-only** predictions.

**This system does not place orders, deposits, or withdrawals.** Predictions are not trading recommendations. Historical simulations do not guarantee future results.

## Repository

```bash
git clone https://github.com/Ora-Kool/forex-trading-lab-dashboard.git
cd forex-trading-lab-dashboard
```

GitHub: [Ora-Kool/forex-trading-lab-dashboard](https://github.com/Ora-Kool/forex-trading-lab-dashboard)

Companion desk UI (Laravel): [Ora-Kool/forex-trading-lab-dashboard](https://github.com/Ora-Kool/forex-trading-lab-dashboard)

---

## Start here (contributors)

**New to the project?** Read **[CONTRIBUTING.md](CONTRIBUTING.md)** end-to-end. It is the authoritative setup guide:

- Recommended device / mode  
- Exact steps for **macOS (bridge)**, **Windows (official)**, **agent**, and **mock**  
- Desk UI (`forextradingai`) wiring  
- Branching, tests, and **how to open a PR**  

Day-to-day ops cheat sheet: **[docs/OPS.md](docs/OPS.md)**  
Mac Wine bridge details: **[docs/MT5_MAC_BRIDGE.md](docs/MT5_MAC_BRIDGE.md)**

---

## Two repositories

| Repository                                                                                              | Responsibility |
|---------------------------------------------------------------------------------------------------------|---|
| **[forexinteligentlab](https://github.com/Ora-Kool/forexinteligentlab)** (this repo) | FastAPI, PostgreSQL, MT5 adapters, collector, ML |
| **[forex-trading-lab-dashboard](https://github.com/Ora-Kool/forex-trading-lab-dashboard)**                                | Laravel + Vue desk, auth, workspaces, `/api` proxy to FastAPI |

---

## Architecture

```text
FBS account
  → MetaTrader 5 (Windows native, or MetaTrader 5.app on Mac)
  → Adapter: official | bridge | agent | mock
  → FastAPI :8088 + PostgreSQL
  → Laravel desk (forextradingai.test) → browser
```

| `MT5_MODE` | Where it runs | Live FBS? |
|---|---|---|
| `bridge` | macOS + MetaTrader 5.app + rpyc | Yes (recommended on Mac) |
| `official` | Windows next to MT5 | Yes (recommended on Windows) |
| `agent` | Backend anywhere; Windows agent pushes data | Yes |
| `mock` | Any OS | No (synthetic) |

---

## Quick start (shortest paths)

### macOS + live FBS (recommended)

```bash
git clone https://github.com/Ora-Kool/forex-trading-lab-dashboard.git
cd forex-trading-lab-dashboard
cp .env.example .env          # set MT5_MODE=bridge and credentials
python3 -m venv .venv && source .venv/bin/activate
pip install -r backend/requirements.txt -r backend/requirements-bridge.txt
createdb forex_intelligence   # once
psql -d forex_intelligence -f database/migrations/001_init.sql

# One-time: open MetaTrader 5.app, log into FBS-Demo, then:
./scripts/mt5_mac_bridge.sh provision
./scripts/mt5_mac_bridge.sh install-client

# Every session:
./scripts/lab.sh start
./scripts/lab.sh status
```

Desk: clone [forex-trading-ai-server](https://github.com/Ora-Kool/forex-trading-ai-server), then open [http://forextradingai.test](http://forextradingai.test).  
Full steps → [CONTRIBUTING.md](CONTRIBUTING.md#6-path-a--macos-with-metatrader-5app-recommended-for-live-fbs-on-mac).

### Windows + live FBS

```bat
set MT5_MODE=official
scripts\run_backend.sh
```

Full steps → [CONTRIBUTING.md](CONTRIBUTING.md#7-path-b--windows-with-official-metatrader5-python).

### No broker (UI / API work)

```bash
# MT5_MODE=mock in .env
./scripts/run_backend.sh
```

---

## Safety rules

The codebase is data + research only. It does not implement:

- automatic order execution  
- deposits / withdrawals  
- martingale or revenge-trading logic  
- guaranteed-profit claims  

Model **accuracy** and strategy **win rate** are different metrics. Win rate is a long-only simulation **after costs**, not “% of direction calls correct.”

Deferred (end of project — do not start unless asked): Stripe, team invites, live trading automation.

---

## Research loop

1. Start the stack (`lab.sh` or `run_backend.sh`)  
2. Settings → Discover / enable majors  
3. Auto-backfill fills `SEED_HISTORY_DAYS` (default 30)  
4. Models → Train  
5. Predictions → Entry / Exit / Δ once the next bar closes  
6. Backtest → cost-adjusted simulation  

---

## Tests

```bash
source .venv/bin/activate
export PYTHONPATH=backend
pytest backend/tests -q
```

Desk: `php artisan test` and `npm run build` in `forextradingai`.

---

## Project layout

```text
backend/app/{api,core,models,schemas,services,ml,mt5,database,workers}
backend/tests
database/migrations
docs/                 OPS.md, MT5_MAC_BRIDGE.md
scripts/              lab.sh, mt5_mac_bridge.sh, run_backend.sh
mt5-agent/            Windows push agent (MT5_MODE=agent)
CONTRIBUTING.md       Full contributor guide
```

---

## API

OpenAPI: [http://127.0.0.1:8088/docs](http://127.0.0.1:8088/docs)

Auth for direct FastAPI calls: `POST /api/auth/login` then `Authorization: Bearer <token>`.  
The desk uses Laravel session + SaaS key to mint workspace-scoped tokens — see CONTRIBUTING.

---

## Pull requests

See **[How to open a pull request](CONTRIBUTING.md#14-how-to-open-a-pull-request)** and the [PR checklist](CONTRIBUTING.md#15-pr-checklist).

Short version:

```bash
git checkout -b feat/your-change
# … work, test …
git push -u origin HEAD
gh pr create
```

Link dual-repo PRs when both the API and the desk change.
