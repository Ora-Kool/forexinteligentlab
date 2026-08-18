"""MT5 collector agent.

Runs on the Windows host where the MetaTrader 5 terminal is installed.
It never places orders. It only reads candles/ticks and posts them to
the Forex Intelligence Lab backend ingest API.

Architecture:
    FBS account -> MT5 terminal -> this agent -> HTTPS -> FastAPI -> PostgreSQL
"""

from __future__ import annotations

import os
import time
from datetime import UTC, datetime

import httpx
from dotenv import load_dotenv

load_dotenv()

BACKEND_URL = os.environ.get("BACKEND_URL", "http://127.0.0.1:8088").rstrip("/")
AGENT_API_KEY = os.environ.get("AGENT_API_KEY", "")
MT5_TERMINAL_PATH = os.environ.get("MT5_TERMINAL_PATH", "")
MT5_LOGIN = os.environ.get("MT5_LOGIN")
MT5_PASSWORD = os.environ.get("MT5_PASSWORD", "")
MT5_SERVER = os.environ.get("MT5_SERVER", "")
SYMBOLS = [item.strip() for item in os.environ.get("AGENT_SYMBOLS", "EURUSD,GBPUSD,USDJPY,XAUUSD").split(",") if item.strip()]
TIMEFRAMES = [item.strip() for item in os.environ.get("AGENT_TIMEFRAMES", "M5").split(",") if item.strip()]
INTERVAL = int(os.environ.get("AGENT_INTERVAL_SECONDS", "5"))

TF_MAP = {"M1": 1, "M5": 5, "M15": 15, "M30": 30, "H1": 16385, "H4": 16388, "D1": 16408}


def connect():
    import MetaTrader5 as mt5

    kwargs = {}
    if MT5_TERMINAL_PATH:
        kwargs["path"] = MT5_TERMINAL_PATH
    if not mt5.initialize(**kwargs):
        return mt5, {"connected": False, "last_error": str(mt5.last_error())}
    if MT5_LOGIN and MT5_PASSWORD and MT5_SERVER:
        if not mt5.login(int(MT5_LOGIN), password=MT5_PASSWORD, server=MT5_SERVER):
            err = str(mt5.last_error())
            mt5.shutdown()
            return mt5, {"connected": False, "last_error": f"login failed: {err}"}
    account = mt5.account_info()
    if account is None:
        return mt5, {"connected": False, "last_error": str(mt5.last_error())}
    return mt5, {
        "connected": True,
        "last_error": "",
        "server": account.server,
        "login": account.login,
        "company": account.company,
        "trade_allowed": False,
    }


def resolve(mt5, requested: str) -> str | None:
    info = mt5.symbol_info(requested)
    if info:
        mt5.symbol_select(requested, True)
        return info.name
    all_symbols = mt5.symbols_get() or []
    base = "".join(ch for ch in requested.upper() if ch.isalpha())
    for item in all_symbols:
        name = item.name.upper()
        if name == requested.upper() or "".join(ch for ch in name if ch.isalpha()) == base:
            mt5.symbol_select(item.name, True)
            return item.name
    return None


def collect(mt5) -> list[dict]:
    candles = []
    for symbol in SYMBOLS:
        resolved = resolve(mt5, symbol)
        if resolved is None:
            print(f"[agent] unknown symbol {symbol}", flush=True)
            continue
        tick = mt5.symbol_info_tick(resolved)
        for timeframe in TIMEFRAMES:
            rates = mt5.copy_rates_from_pos(resolved, TF_MAP[timeframe], 0, 5)
            if rates is None:
                print(f"[agent] no rates for {resolved} {timeframe}: {mt5.last_error()}", flush=True)
                continue
            for row in rates:
                candles.append(
                    {
                        "symbol": resolved,
                        "timeframe": timeframe,
                        "timestamp": datetime.fromtimestamp(int(row["time"]), tz=UTC).isoformat(),
                        "open": float(row["open"]),
                        "high": float(row["high"]),
                        "low": float(row["low"]),
                        "close": float(row["close"]),
                        "tick_volume": int(row["tick_volume"]),
                        "real_volume": int(row["real_volume"]) if "real_volume" in row.dtype.names else 0,
                        "bid": float(tick.bid) if tick else None,
                        "ask": float(tick.ask) if tick else None,
                        "spread": float(tick.ask - tick.bid) if tick else None,
                    }
                )
    return candles


def main() -> None:
    if not AGENT_API_KEY:
        raise SystemExit("AGENT_API_KEY is required")
    print("[agent] starting research-only MT5 collector (no orders)", flush=True)
    while True:
        mt5, status = connect()
        candles = collect(mt5) if status.get("connected") else []
        try:
            response = httpx.post(
                f"{BACKEND_URL}/api/agent/ingest",
                headers={"X-Agent-Key": AGENT_API_KEY},
                json={"status": status, "candles": candles},
                timeout=30,
            )
            print(f"[agent] ingest {response.status_code} candles={len(candles)} connected={status.get('connected')}", flush=True)
        except Exception as exc:
            print(f"[agent] backend post failed: {exc}", flush=True)
        try:
            mt5.shutdown()
        except Exception:
            pass
        time.sleep(INTERVAL)


if __name__ == "__main__":
    main()
