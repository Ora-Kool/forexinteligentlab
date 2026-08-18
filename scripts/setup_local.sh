#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

if [[ ! -f .env ]]; then
  cp .env.example .env
  echo "Created .env from .env.example — edit credentials before using a live MT5 terminal."
fi

if ! command -v psql >/dev/null; then
  echo "psql not found. Install PostgreSQL locally (Homebrew: brew install postgresql@18 && brew services start postgresql@18)"
  exit 1
fi

createdb forex_intelligence 2>/dev/null || true
psql -d forex_intelligence -f "$ROOT/database/migrations/001_init.sql"

python3 -m venv .venv
# shellcheck disable=SC1091
source .venv/bin/activate
pip install -r backend/requirements.txt

cd "$ROOT/frontend"
npm install

echo
echo "Setup complete."
echo "1. Review .env"
echo "2. ./scripts/run_backend.sh"
echo "4. Open http://127.0.0.1:5173"
