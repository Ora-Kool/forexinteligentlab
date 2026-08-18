# Contributing to Forex Intelligence Lab

Thank you for helping. This project is a **research desk** for FBS / MetaTrader 5 market data. It does **not** place trades. Do not add order-send paths, deposit/withdraw flows, or “guaranteed profit” language.

The product spans **two repositories**:

| Repo | Role |
|---|---|
| `forexinteligentlab` (this repo) | FastAPI, MT5 adapters, collector, ML, PostgreSQL, ops scripts |
| `forextradingai` | Laravel + Vue desk UI (Herd), auth, workspaces, API proxy |

PRs that change the desk UI usually live in `forextradingai`. PRs that change market data, models, or MT5 live here. Cross-cutting changes need **two PRs** (or one PR per repo) linked in the descriptions.

---

## Table of contents

1. [Code of conduct (brief)](#1-code-of-conduct-brief)
2. [What you will build](#2-what-you-will-build)
3. [Recommended setup](#3-recommended-setup)
4. [Device matrix — pick your path](#4-device-matrix--pick-your-path)
5. [Prerequisites (all devices)](#5-prerequisites-all-devices)
6. [Path A — macOS with MetaTrader 5.app (recommended for live FBS on Mac)](#6-path-a--macos-with-metatrader-5app-recommended-for-live-fbs-on-mac)
7. [Path B — Windows with official MetaTrader5 Python](#7-path-b--windows-with-official-metatrader5-python)
8. [Path C — Backend anywhere + Windows mt5-agent](#8-path-c--backend-anywhere--windows-mt5-agent)
9. [Path D — Mock mode (no broker, fastest for UI/API work)](#9-path-d--mock-mode-no-broker-fastest-for-uiapi-work)
10. [Desk UI (`forextradingai`)](#10-desk-ui-forextradingai)
11. [Day-to-day commands](#11-day-to-day-commands)
12. [Development workflow](#12-development-workflow)
13. [Tests](#13-tests)
14. [How to open a pull request](#14-how-to-open-a-pull-request)
15. [PR checklist](#15-pr-checklist)
16. [Architecture notes for contributors](#16-architecture-notes-for-contributors)
17. [Deferred (do not start unless asked)](#17-deferred-do-not-start-unless-asked)
18. [Getting help](#18-getting-help)

---

## 1. Code of conduct (brief)

- Be respectful in issues and reviews.
- Assume research-only intent: no silent order placement.
- Never commit secrets (`.env`, MT5 passwords, API keys, production dump files).
- Prefer small, reviewable PRs over mega-diffs.

---

## 2. What you will build

```text
FBS account
  → MetaTrader 5 (Windows native, or MetaTrader 5.app / Wine on Mac)
  → MT5 adapter (official | bridge | agent | mock)
  → FastAPI (this repo) + PostgreSQL
  → Laravel desk (forextradingai) → browser
```

Safety invariants:

- `trading_enabled` stays false in the SaaS broker form.
- Collectors read candles/ticks only.
- Predictions are research labels (Entry / Exit / Δ), not trade tickets.

---

## 3. Recommended setup

| Goal | Recommended device | `MT5_MODE` |
|---|---|---|
| **Contribute with live FBS on a Mac** | Apple Silicon / Intel Mac + MetaTrader 5.app | `bridge` |
| **Contribute with live FBS on Windows** | Windows 10/11 PC or VPS next to MT5 | `official` |
| **Backend on Mac/Linux, MT5 on another Windows box** | Two machines | `agent` |
| **UI / API / ML without a broker** | Any Mac/Linux/Windows | `mock` |

**Recommended for most Mac contributors:** Path A (`bridge`).  
**Recommended for production-like Windows hosts:** Path B (`official`).  
**Fastest onboarding for frontend-only:** Path D (`mock`).

---

## 4. Device matrix — pick your path

| Device | Live FBS? | What to install | Start command |
|---|---|---|---|
| **macOS + MT5.app** | Yes | PostgreSQL, Python 3.11+, Node 20+, MetaTrader 5.app, Herd (desk) | `./scripts/lab.sh start` |
| **Windows + MT5** | Yes | PostgreSQL, Python 3.11+, Node 20+, MetaTrader 5, (Herd or Laravel locally for desk) | `./scripts/run_backend.sh` with `MT5_MODE=official` |
| **Linux / Mac backend + remote Windows MT5** | Yes | Backend host + Windows agent | Backend `MT5_MODE=agent`; agent `python agent.py` |
| **Any OS, no MT5** | No (synthetic) | PostgreSQL, Python, Node | `MT5_MODE=mock` + `./scripts/run_backend.sh` |

Detailed ops: [docs/OPS.md](docs/OPS.md). Mac bridge deep dive: [docs/MT5_MAC_BRIDGE.md](docs/MT5_MAC_BRIDGE.md).

---

## 5. Prerequisites (all devices)

Install these **before** cloning adapters:

1. **Git**
2. **Python 3.11+** (3.12–3.14 OK if wheels install)
3. **Node.js 20+** and npm
4. **PostgreSQL 14+**
5. For the Vue desk: **Laravel Herd** (macOS/Windows) or equivalent PHP 8.3+ + Nginx pointing at `forextradingai`

Create the database once:

```bash
createdb forex_intelligence
# or: psql -c "CREATE DATABASE forex_intelligence;"
```

---

## 6. Path A — macOS with MetaTrader 5.app (recommended for live FBS on Mac)

### A.1 Clone and Python env

```bash
git clone <this-repo-url> forexinteligentlab
cd forexinteligentlab
cp .env.example .env
python3 -m venv .venv
source .venv/bin/activate
pip install -r backend/requirements.txt
pip install -r backend/requirements-bridge.txt
psql -d forex_intelligence -f database/migrations/001_init.sql
# If the DB already exists from an older clone, also apply:
# psql -d forex_intelligence -f database/migrations/002_workspace.sql
# psql -d forex_intelligence -f database/migrations/003_prediction_exit_price.sql
```

### A.2 Configure `.env` (backend)

Set at least:

```env
MT5_MODE=bridge
MT5_LOGIN=<your_fbs_login>
MT5_PASSWORD=<your_mt5_password>
MT5_SERVER=FBS-Demo
MT5_TERMINAL_PATH=C:/Program Files/MetaTrader 5/terminal64.exe
MT5_BRIDGE_HOST=127.0.0.1
MT5_BRIDGE_PORT=18813
SEED_HISTORY_DAYS=30
AUTO_BACKFILL=true
DATABASE_URL=postgresql+psycopg://YOUR_USER@localhost:5432/forex_intelligence
SAAS_API_KEY=local-fil-saas-key-2026
DASHBOARD_USERNAME=admin
DASHBOARD_PASSWORD=<choose-a-local-password>
APP_SECRET_KEY=<long-random-string>
```

Never commit `.env`.

### A.3 One-time Wine bridge provision

1. Install **MetaTrader 5** for macOS and open it.
2. Log into **FBS** (`File → Open an Account` → search `FBS Markets Inc.` → existing account → `FBS-Demo`).
3. Wait until the status bar shows a live ping (not “No connection”).
4. From the repo:

```bash
./scripts/mt5_mac_bridge.sh provision
./scripts/mt5_mac_bridge.sh install-client
./scripts/mt5_mac_bridge.sh doctor   # should show FBS-Demo among connected servers
./scripts/mt5_mac_bridge.sh smoke   # account + bars + tick
```

### A.4 Start every day

```bash
# From repo root — not from scripts/ unless you use ./lab.sh
./scripts/lab.sh start
./scripts/lab.sh status
```

Order of processes (handled by `lab.sh`):

1. MetaTrader 5.app  
2. rpyc bridge on `:18813`  
3. FastAPI on `:8088`

Then start the desk (section 10).

### A.5 Common Mac mistakes

| Mistake | Fix |
|---|---|
| `zsh: command not found: lab.sh` | Use `./scripts/lab.sh` from repo root, or `./lab.sh` **inside** `scripts/` |
| `-6 Authorization failed` | Log into FBS inside MT5 first; generic MetaQuotes-Demo will reject FBS logins |
| `-10003 terminal not found` | Set `MT5_TERMINAL_PATH` to the Wine path above |
| Bridge dies when terminal closes | Keep MT5 open; services are detached via `lab.sh` but still need the terminal |

---

## 7. Path B — Windows with official MetaTrader5 Python

### B.1 Install MT5 and log in

1. Install MetaTrader 5 (FBS build or MetaQuotes).
2. Log into FBS-Demo / your assigned server.
3. Confirm Market Watch symbols are visible.

### B.2 Backend

```bat
git clone <this-repo-url> forexinteligentlab
cd forexinteligentlab
copy .env.example .env
python -m venv .venv
.venv\Scripts\activate
pip install -r backend\requirements.txt
psql -d forex_intelligence -f database\migrations\001_init.sql
```

`.env`:

```env
MT5_MODE=official
MT5_LOGIN=...
MT5_PASSWORD=...
MT5_SERVER=FBS-Demo
MT5_TERMINAL_PATH=C:\Program Files\MetaTrader 5\terminal64.exe
```

Start:

```bat
scripts\run_backend.sh
rem or:
set PYTHONPATH=backend
uvicorn app.main:app --host 127.0.0.1 --port 8088
```

**Do not** set `MT5_MODE=bridge` on Windows. Leave `OfficialMT5Connector` alone unless you are fixing a Windows-specific bug.

---

## 8. Path C — Backend anywhere + Windows mt5-agent

Use when FastAPI cannot run on the same OS as MT5.

**On the backend host**

```env
MT5_MODE=agent
AGENT_API_KEY=<shared-secret>
```

**On the Windows MT5 host**

```bat
cd mt5-agent
python -m pip install -r requirements.txt
copy .env.example .env
rem set BACKEND_URL=http://<backend>:8088
rem set AGENT_API_KEY=<same-secret>
rem set MT5_LOGIN / MT5_PASSWORD / MT5_SERVER
python agent.py
```

The agent only **reads** candles/ticks and POSTs to `/api/agent/ingest`. It must never send orders.

---

## 9. Path D — Mock mode (no broker, fastest for UI/API work)

```bash
cd forexinteligentlab
cp .env.example .env
# set MT5_MODE=mock and DATABASE_URL
python3 -m venv .venv && source .venv/bin/activate
pip install -r backend/requirements.txt
psql -d forex_intelligence -f database/migrations/001_init.sql
./scripts/run_backend.sh
```

Synthetic majors are seeded for local dashboard work. Do not treat mock prices as market data.

---

## 10. Desk UI (`forextradingai`)

Clone next to the lab (paths may differ on your machine):

```bash
git clone <forextradingai-url> forextradingai
cd forextradingai
cp .env.example .env   # if present
```

`.env` essentials:

```env
APP_URL=http://forextradingai.test
PYTHON_API_URL=http://127.0.0.1:8088
PYTHON_SAAS_KEY=<must match SAAS_API_KEY in the lab .env>
VITE_PYTHON_WS_URL=ws://127.0.0.1:8088
```

Then:

```bash
composer install
php artisan key:generate
php artisan migrate
npm install
npm run build    # or: npm run dev
```

Open [http://forextradingai.test](http://forextradingai.test) (Herd).

Register a desk user in the UI (Laravel auth). The Settings **broker label** stores login/server metadata only — it does **not** replace Path A/B/C credentials.

---

## 11. Day-to-day commands

```bash
# Mac live stack
./scripts/lab.sh start | status | stop | restart | smoke

# Backend only
./scripts/run_backend.sh

# Bridge diagnostics (Mac)
./scripts/mt5_mac_bridge.sh doctor
./scripts/mt5_mac_bridge.sh smoke

# Health
curl -s http://127.0.0.1:8088/api/health
```

Research loop after the stack is up:

1. Settings → Discover / Enable research majors  
2. Wait for auto-backfill (`SEED_HISTORY_DAYS`) or Import manually  
3. Models → Train  
4. Predictions (Entry / Exit / Δ)  
5. Backtest  

---

## 12. Development workflow

1. **Fork** (or get write access) and **clone** both repos you need.
2. Create a branch from the default branch (`main` / `master` — check with `git status` / `git remote show origin`):

```bash
git checkout -b feat/short-description
# or: fix/...  docs/...  chore/...
```

3. Keep changes scoped. Prefer one concern per PR.
4. Run relevant tests before pushing (section 13).
5. Commit with a clear message focused on **why**:

```bash
git add -p
git commit -m "$(cat <<'EOF'
Explain the reason for the change in 1–2 sentences.

EOF
)"
```

6. Push and open a PR (section 14).

Branch naming suggestions:

| Prefix | Use |
|---|---|
| `feat/` | New behavior |
| `fix/` | Bug fix |
| `docs/` | Documentation only |
| `chore/` | Tooling, deps, scripts |
| `refactor/` | No intended behavior change |

---

## 13. Tests

### This repo (FastAPI)

```bash
cd forexinteligentlab
source .venv/bin/activate
export PYTHONPATH=backend
pytest backend/tests -q
```

Useful subsets:

```bash
pytest backend/tests/test_bridge_mode.py backend/tests/test_backfill.py -q
pytest backend/tests/test_tenant.py -q
```

### Desk (`forextradingai`)

```bash
cd forextradingai
php artisan test
npm run build
```

Do not commit `public/build` churn unless your team’s workflow requires built assets in git (this project currently builds assets for Herd).

---

## 14. How to create a pull request

### Using GitHub CLI (`gh`) — preferred

```bash
git push -u origin HEAD
gh pr create --title "Short imperative summary" --body "$(cat <<'EOF'
## Summary
- What changed and why

## Device / mode tested
- [ ] mock
- [ ] bridge (macOS)
- [ ] official (Windows)
- [ ] agent

## Test plan
- [ ] `pytest …` / `php artisan test` / `npm run build`
- [ ] Manual: health, monitor, train (if relevant)

## Notes
- Linked PR in the other repo (if any): …
- Explicitly does NOT enable order placement
EOF
)"
```

### Using the GitHub website

1. Push your branch.
2. Open the repo → **Compare & pull request**.
3. Fill the same Summary / Device / Test plan sections.
4. Request review from a maintainer.
5. Respond to review comments with new commits (prefer not force-pushing unless asked).

### Dual-repo changes

If you change the FastAPI contract **and** the Vue client:

1. Open the backend PR first (or together).
2. In the desk PR body, link the backend PR.
3. Keep API compatibility or document breaking changes clearly.

---

## 15. PR checklist

Before you mark a PR ready:

- [ ] No secrets in the diff (`.env`, passwords, keys)
- [ ] No order-send / trading automation enabled
- [ ] Windows `official` / `agent` adapters untouched unless the PR is specifically about them
- [ ] Mac bridge changes confined to `bridge*` modules + scripts/docs
- [ ] Tests added or updated when behavior changes
- [ ] Docs updated if setup/commands changed (`README`, `CONTRIBUTING`, `docs/OPS.md`, `docs/MT5_MAC_BRIDGE.md`)
- [ ] Desk UI still loads on desktop and mobile widths for UI PRs

---

## 16. Architecture notes for contributors

| Area | Location | Notes |
|---|---|---|
| MT5 factory | `backend/app/mt5/factory.py` | `mock` / `official` / `agent` / `bridge` |
| Mac bridge | `backend/app/mt5/bridge*.py`, `scripts/lab.sh` | Wraps official after rpyc bootstrap |
| Auto-backfill | `backend/app/services/backfill.py` | Runs once when collector starts |
| Predictions | `backend/app/services/predictions.py` | Stores `price` (entry) + `exit_price` |
| Tenant scope | `workspace_id` on models + Laravel SaaS key | Desk injects workspace via gateway |
| Metrics JSON | `backend/app/ml/metrics.py` | Must be NaN-safe for Postgres JSONB |

---

## 17. Deferred (do not start unless asked)

These are intentionally **end of project**, not current contribution focus:

- Stripe / billing  
- Multi-member team invites  
- Live account mode  
- Order automation / Phase 3 demo execution  

If an issue asks for these, confirm with maintainers first.

---

## 18. Getting help

1. Run `./scripts/lab.sh status` (Mac) or `curl localhost:8088/api/health`.
2. Mac bridge: `./scripts/mt5_mac_bridge.sh doctor`.
3. Check `.run/logs/backend.log` and `.run/logs/bridge.log`.
4. Open an issue with: OS, `MT5_MODE`, health JSON, and the failing command (redact passwords).

Welcome aboard — keep it research-only, keep PRs small, and document the path you actually tested.
