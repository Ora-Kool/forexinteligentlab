#!/usr/bin/env python3
"""Read one account snapshot and a few candles through the macOS Wine bridge."""

from __future__ import annotations

import os

import mt5_mac_bridge as mt5b


def main() -> int:
    try:
        handle = mt5b.init(
            backend="bridge",
            host=os.environ.get("MT5_BRIDGE_HOST", "127.0.0.1"),
            port=int(os.environ.get("MT5_BRIDGE_PORT", "18813")),
            login=os.environ.get("MT5_LOGIN") or None,
            password=os.environ.get("MT5_PASSWORD") or None,
            server=os.environ.get("MT5_SERVER") or None,
        )
    except RuntimeError as exc:
        print(f"bridge init failed: {exc}")
        return 1
    try:
        account = handle.mt5.account_info()
        if account is None:
            print("account: none authorized")
            return 1
        print(f"account: {account.login} on {account.server} ({account.company})")
        rates = handle.mt5.copy_rates_from_pos("EURUSD", handle.mt5.TIMEFRAME_M5, 0, 3)
        print(f"bars: {0 if rates is None else len(rates)}")
        tick = handle.mt5.symbol_info_tick("EURUSD")
        print(f"tick: {tick}")
        return 0
    finally:
        mt5b.shutdown(handle)


if __name__ == "__main__":
    raise SystemExit(main())
