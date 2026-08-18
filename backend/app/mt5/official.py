"""Official MetaTrader5 Python connector (Windows host with a running terminal).

This module never sends orders. It only reads account/terminal metadata,
symbol lists, ticks, and historical/realtime candles.
"""

from __future__ import annotations

from datetime import UTC, datetime

from app.core.config import get_settings
from app.core.constants import SYMBOL_SUFFIXES, TIMEFRAME_MT5
from app.mt5.base import CandleRecord, MT5Connector, MT5Status, SymbolInfo, TickRecord


def _import_mt5():
    try:
        import MetaTrader5 as mt5  # type: ignore
    except ImportError as exc:
        raise RuntimeError(
            "The MetaTrader5 package is not installed. "
            "It is Windows-only. Run the collector on the MT5 host "
            "or use MT5_MODE=mock / MT5_MODE=agent."
        ) from exc
    return mt5


def _as_utc(value) -> datetime:
    if isinstance(value, datetime):
        return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)
    return datetime.fromtimestamp(int(value), tz=UTC)


def _base_code(name: str) -> str:
    return "".join(ch for ch in name.upper() if ch.isalpha())


class OfficialMT5Connector(MT5Connector):
    def __init__(self) -> None:
        self._mt5 = None
        self._connected = False
        self._error = ""
        self._status = MT5Status(connected=False, mode="official")

    def connect(self) -> MT5Status:
        settings = get_settings()
        mt5 = _import_mt5()
        self._mt5 = mt5
        kwargs: dict = {"timeout": settings.mt5_timeout_ms}
        if settings.mt5_terminal_path:
            kwargs["path"] = settings.mt5_terminal_path
        if not mt5.initialize(**kwargs):
            self._connected = False
            self._error = f"MT5 initialize failed: {mt5.last_error()}"
            self._status = MT5Status(connected=False, mode="official", last_error=self._error)
            return self._status

        if settings.mt5_login and settings.mt5_password and settings.mt5_server:
            authorized = mt5.login(
                int(settings.mt5_login),
                password=settings.mt5_password,
                server=settings.mt5_server,
            )
            if not authorized:
                self._error = f"MT5 login failed: {mt5.last_error()}"
                mt5.shutdown()
                self._connected = False
                self._status = MT5Status(connected=False, mode="official", last_error=self._error)
                return self._status

        info = mt5.terminal_info()
        account = mt5.account_info()
        if account is None:
            self._error = f"MT5 connected but account_info is empty: {mt5.last_error()}"
            self._connected = False
            self._status = MT5Status(connected=False, mode="official", last_error=self._error)
            return self._status

        self._connected = True
        self._error = ""
        self._status = MT5Status(
            connected=True,
            mode="official",
            terminal=getattr(info, "name", "MetaTrader 5") if info else "MetaTrader 5",
            server=account.server,
            login=account.login,
            company=account.company,
            trade_allowed=False,
            last_error="",
            symbols_available=len(mt5.symbols_get() or []),
            details={
                "research_only": True,
                "orders_disabled": True,
                "balance_hidden": True,
            },
        )
        return self._status

    def disconnect(self) -> None:
        if self._mt5 is not None:
            try:
                self._mt5.shutdown()
            except Exception:
                pass
        self._connected = False

    def status(self) -> MT5Status:
        if self._connected and self._mt5 is not None:
            terminal = self._mt5.terminal_info()
            if terminal is None:
                self._connected = False
                self._error = f"MT5 terminal lost: {self._mt5.last_error()}"
                self._status.last_error = self._error
                self._status.connected = False
        return self._status

    def discover_symbols(self, query: str | None = None) -> list[SymbolInfo]:
        self._require()
        raw = self._mt5.symbols_get()
        if raw is None:
            raise RuntimeError(f"symbols_get failed: {self._mt5.last_error()}")
        items = []
        for item in raw:
            name = item.name
            if query and query.upper() not in name.upper() and query.upper() not in (item.description or "").upper():
                continue
            items.append(
                SymbolInfo(
                    name=name,
                    description=item.description or "",
                    digits=int(item.digits),
                    point=float(item.point),
                    contract_size=float(getattr(item, "trade_contract_size", 0) or 0),
                    visible=bool(item.visible),
                    base_code=_base_code(name),
                )
            )
        return items

    def resolve_symbol(self, requested: str) -> SymbolInfo | None:
        self._require()
        info = self._mt5.symbol_info(requested)
        if info is not None:
            self._mt5.symbol_select(requested, True)
            return SymbolInfo(
                name=info.name,
                description=info.description or "",
                digits=int(info.digits),
                point=float(info.point),
                contract_size=float(getattr(info, "trade_contract_size", 0) or 0),
                visible=True,
                base_code=_base_code(info.name),
            )
        discovered = self.discover_symbols()
        base = _base_code(requested)
        ranked: list[SymbolInfo] = []
        for symbol in discovered:
            if symbol.name.upper() == requested.upper() or _base_code(symbol.name) == base:
                ranked.append(symbol)
        for suffix in SYMBOL_SUFFIXES:
            match = next((s for s in ranked if s.name.upper() == f"{base}{suffix}".upper()), None)
            if match:
                self._mt5.symbol_select(match.name, True)
                return match
        if ranked:
            ranked.sort(key=lambda s: len(s.name))
            self._mt5.symbol_select(ranked[0].name, True)
            return ranked[0]
        return None

    def copy_rates_range(self, symbol: str, timeframe: str, date_from: datetime, date_to: datetime) -> list[CandleRecord]:
        self._require()
        tf = TIMEFRAME_MT5[timeframe]
        start = date_from.astimezone(UTC) if date_from.tzinfo else date_from.replace(tzinfo=UTC)
        end = date_to.astimezone(UTC) if date_to.tzinfo else date_to.replace(tzinfo=UTC)
        rates = self._mt5.copy_rates_range(symbol, tf, start, end)
        if rates is None:
            raise RuntimeError(f"copy_rates_range failed for {symbol} {timeframe}: {self._mt5.last_error()}")
        tick = self.symbol_tick(symbol)
        return [self._to_candle(symbol, timeframe, row, tick) for row in rates]

    def copy_rates_from_pos(self, symbol: str, timeframe: str, start: int, count: int) -> list[CandleRecord]:
        self._require()
        tf = TIMEFRAME_MT5[timeframe]
        rates = self._mt5.copy_rates_from_pos(symbol, tf, start, count)
        if rates is None:
            raise RuntimeError(f"copy_rates_from_pos failed for {symbol} {timeframe}: {self._mt5.last_error()}")
        tick = self.symbol_tick(symbol)
        return [self._to_candle(symbol, timeframe, row, tick) for row in rates]

    def symbol_tick(self, symbol: str) -> TickRecord | None:
        self._require()
        tick = self._mt5.symbol_info_tick(symbol)
        if tick is None:
            return None
        return TickRecord(
            symbol=symbol,
            timestamp=_as_utc(tick.time),
            bid=float(tick.bid),
            ask=float(tick.ask),
            last=float(tick.last or tick.bid),
            volume=int(getattr(tick, "volume", 0) or 0),
        )

    def _to_candle(self, symbol: str, timeframe: str, row, tick: TickRecord | None) -> CandleRecord:
        spread = None
        bid = tick.bid if tick else None
        ask = tick.ask if tick else None
        if bid is not None and ask is not None:
            spread = ask - bid
        return CandleRecord(
            symbol=symbol,
            timeframe=timeframe,
            timestamp=_as_utc(row["time"]),
            open=float(row["open"]),
            high=float(row["high"]),
            low=float(row["low"]),
            close=float(row["close"]),
            tick_volume=int(row["tick_volume"]),
            real_volume=int(row["real_volume"]) if "real_volume" in row.dtype.names else 0,
            spread=spread,
            bid=bid,
            ask=ask,
        )

    def _require(self) -> None:
        if not self._connected or self._mt5 is None:
            raise RuntimeError(self._error or "MT5 is not connected")
