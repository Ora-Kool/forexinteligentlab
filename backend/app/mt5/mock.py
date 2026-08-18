"""Synthetic FBS-like market data for local development and tests.

This connector never talks to a real broker. It exists so the research
platform can run on macOS/Linux without MetaTrader 5.
"""

from __future__ import annotations

import hashlib
import math
import threading
from datetime import UTC, datetime, timedelta

from app.core.constants import PREFERRED_BASES, SYMBOL_SUFFIXES, TIMEFRAME_MINUTES, pip_size_for
from app.mt5.base import CandleRecord, MT5Connector, MT5Status, SymbolInfo, TickRecord


def _seed_int(text: str) -> int:
    return int(hashlib.sha256(text.encode()).hexdigest()[:8], 16)


def _base_price(symbol: str) -> float:
    mapping = {
        "EURUSD": 1.08540,
        "GBPUSD": 1.27120,
        "USDJPY": 149.820,
        "USDCHF": 0.88740,
        "AUDUSD": 0.66210,
        "USDCAD": 1.36450,
        "NZDUSD": 0.59880,
        "EURGBP": 0.85360,
        "GBPJPY": 190.450,
        "EURJPY": 162.580,
        "XAUUSD": 2384.60,
    }
    for key, value in mapping.items():
        if key in symbol.upper():
            return value
    return 1.10000


def _digits(symbol: str) -> int:
    if "XAU" in symbol.upper() or "JPY" in symbol.upper():
        return 3
    return 5


class MockMT5Connector(MT5Connector):
    def __init__(self, fail_connect: bool = False, available: bool | None = None) -> None:
        self.fail_connect = fail_connect
        self._available = True if available is None else available
        self._connected = False
        self._lock = threading.Lock()
        self._symbols = self._build_symbols()
        self._error = ""

    def _build_symbols(self) -> list[SymbolInfo]:
        symbols: list[SymbolInfo] = []
        for base in PREFERRED_BASES:
            # Include suffix variants so discovery/matching can be tested.
            for suffix in ("", ".a", "m"):
                name = f"{base}{suffix}"
                symbols.append(
                    SymbolInfo(
                        name=name,
                        description=f"{base} mock FBS symbol",
                        digits=_digits(base),
                        point=10 ** (-_digits(base)),
                        contract_size=100.0 if "XAU" in base else 100000.0,
                        visible=True,
                        base_code=base,
                    )
                )
        symbols.append(
            SymbolInfo(
                name="BTCUSD",
                description="Bitcoin (not in default watchlist)",
                digits=2,
                point=0.01,
                visible=True,
                base_code="BTCUSD",
            )
        )
        return symbols

    def connect(self) -> MT5Status:
        if self.fail_connect or not self._available:
            self._connected = False
            self._error = "MT5 terminal unavailable (mock failure)"
            return self.status()
        self._connected = True
        self._error = ""
        return self.status()

    def disconnect(self) -> None:
        self._connected = False

    def status(self) -> MT5Status:
        return MT5Status(
            connected=self._connected,
            mode="mock",
            terminal="Mock MetaTrader 5",
            server="FBS-Demo-Mock",
            login=12345678,
            company="FBS (simulated)",
            trade_allowed=False,
            last_error=self._error,
            symbols_available=len(self._symbols) if self._connected else 0,
            details={"research_only": True, "orders_disabled": True},
        )

    def discover_symbols(self, query: str | None = None) -> list[SymbolInfo]:
        self._require()
        items = self._symbols
        if query:
            q = query.upper()
            items = [s for s in items if q in s.name.upper() or q in s.description.upper()]
        return items

    def resolve_symbol(self, requested: str) -> SymbolInfo | None:
        self._require()
        exact = next((s for s in self._symbols if s.name.upper() == requested.upper()), None)
        if exact:
            return exact
        base = "".join(ch for ch in requested.upper() if ch.isalpha())
        candidates = [s for s in self._symbols if s.base_code == base or s.name.upper().startswith(base)]
        # Prefer unsuffixed exact base, then shortest name.
        candidates.sort(key=lambda s: (0 if s.name.upper() == base else 1, len(s.name)))
        return candidates[0] if candidates else None

    def copy_rates_range(
        self,
        symbol: str,
        timeframe: str,
        date_from: datetime,
        date_to: datetime,
    ) -> list[CandleRecord]:
        self._require()
        info = self.resolve_symbol(symbol)
        if info is None:
            raise ValueError(f"Unknown symbol: {symbol}")
        start = date_from.astimezone(UTC) if date_from.tzinfo else date_from.replace(tzinfo=UTC)
        end = date_to.astimezone(UTC) if date_to.tzinfo else date_to.replace(tzinfo=UTC)
        minutes = TIMEFRAME_MINUTES[timeframe]
        aligned = start.replace(second=0, microsecond=0)
        remainder = aligned.minute % minutes
        if remainder:
            aligned += timedelta(minutes=minutes - remainder)
        candles: list[CandleRecord] = []
        cursor = aligned
        while cursor <= end:
            candles.append(self._candle_at(info.name, timeframe, cursor))
            cursor += timedelta(minutes=minutes)
        return candles

    def copy_rates_from_pos(self, symbol: str, timeframe: str, start: int, count: int) -> list[CandleRecord]:
        end = datetime.now(UTC)
        minutes = TIMEFRAME_MINUTES[timeframe]
        date_to = end - timedelta(minutes=minutes * start)
        date_from = date_to - timedelta(minutes=minutes * max(count, 1))
        return self.copy_rates_range(symbol, timeframe, date_from, date_to)[-count:]

    def symbol_tick(self, symbol: str) -> TickRecord | None:
        self._require()
        info = self.resolve_symbol(symbol)
        if info is None:
            return None
        now = datetime.now(UTC)
        candle = self._candle_at(info.name, "M1", now.replace(second=0, microsecond=0))
        pip = pip_size_for(info.name)
        spread = pip * 0.8
        return TickRecord(
            symbol=info.name,
            timestamp=now,
            bid=candle.close,
            ask=candle.close + spread,
            last=candle.close,
            volume=candle.tick_volume,
        )

    def _require(self) -> None:
        if not self._connected:
            raise RuntimeError(self._error or "MT5 is not connected")

    def _candle_at(self, symbol: str, timeframe: str, ts: datetime) -> CandleRecord:
        minutes = TIMEFRAME_MINUTES[timeframe]
        epoch = int(ts.timestamp() // (minutes * 60))
        seed = _seed_int(f"{symbol}:{timeframe}:{epoch}")
        rng_a = (seed % 10_000) / 10_000
        rng_b = ((seed // 10_000) % 10_000) / 10_000
        rng_c = ((seed // 100_000_000) % 10_000) / 10_000
        base = _base_price(symbol)
        # Slow drift + bar noise. Deterministic per timestamp so re-imports match.
        drift = math.sin(epoch / 180.0) * base * 0.004
        noise = (rng_a - 0.5) * base * 0.0012
        close = base + drift + noise
        amplitude = max(base * 0.00035, pip_size_for(symbol) * 6)
        high = close + amplitude * (0.4 + rng_b)
        low = close - amplitude * (0.4 + rng_c)
        open_ = close + (rng_b - rng_c) * amplitude
        high = max(high, open_, close)
        low = min(low, open_, close)
        pip = pip_size_for(symbol)
        spread = pip * (0.6 + rng_a * 0.8)
        digits = _digits(symbol)
        return CandleRecord(
            symbol=symbol,
            timeframe=timeframe,
            timestamp=ts.astimezone(UTC),
            open=round(open_, digits),
            high=round(high, digits),
            low=round(low, digits),
            close=round(close, digits),
            tick_volume=int(80 + rng_a * 400),
            real_volume=0,
            spread=round(spread, digits + 1),
            bid=round(close, digits),
            ask=round(close + spread, digits),
        )
