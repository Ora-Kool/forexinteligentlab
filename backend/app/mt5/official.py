"""Official MetaTrader5 Python connector (Windows host with a running terminal).

This module never sends orders. It only reads account/terminal metadata,
symbol lists, ticks, and historical/realtime candles.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from app.core.config import get_settings
from app.core.constants import SYMBOL_SUFFIXES, TIMEFRAME_MT5
from app.core.logging import get_logger
from app.mt5.base import CandleRecord, MT5Connector, MT5Status, SymbolInfo, TickRecord

log = get_logger(__name__)

# MetaTrader reports candle/tick times as epoch seconds built from the *broker
# server* wall clock, not UTC. Treating them as UTC shifts every bar by the
# server offset (FBS runs EET/EEST, so +2h or +3h), which corrupts hour_of_day
# and the session flags. Detect the offset from a live tick and correct it.
OFFSET_PROBE_SYMBOLS = ("EURUSD", "GBPUSD", "USDJPY", "XAUUSD")
MAX_PLAUSIBLE_OFFSET_MINUTES = 14 * 60
OFFSET_ROUNDING_MINUTES = 15


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
    """Read a raw MT5 time as an aware datetime, still on the server clock."""
    if isinstance(value, datetime):
        return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)
    return datetime.fromtimestamp(int(value), tz=UTC)


def _round_offset_minutes(seconds: float) -> int:
    minutes = seconds / 60
    return int(round(minutes / OFFSET_ROUNDING_MINUTES) * OFFSET_ROUNDING_MINUTES)


def _base_code(name: str) -> str:
    return "".join(ch for ch in name.upper() if ch.isalpha())


class OfficialMT5Connector(MT5Connector):
    def __init__(self) -> None:
        self._mt5 = None
        self._connected = False
        self._error = ""
        self._status = MT5Status(connected=False, mode="official")
        self._server_offset: timedelta | None = None
        self._point_cache: dict[str, float] = {}

    def _detect_server_offset(self) -> timedelta:
        """Server clock minus UTC, from the freshest tick we can find.

        A configured ``MT5_SERVER_UTC_OFFSET_MINUTES`` always wins. Auto-detection
        needs a live tick, so outside market hours the newest tick is stale and
        the measurement is rejected as implausible, falling back to zero.
        """
        configured = get_settings().mt5_server_utc_offset_minutes
        if configured is not None:
            return timedelta(minutes=int(configured))

        now = datetime.now(UTC)
        best: float | None = None
        for symbol in OFFSET_PROBE_SYMBOLS:
            try:
                tick = self._mt5.symbol_info_tick(symbol)
            except Exception:
                continue
            if tick is None or not getattr(tick, "time", None):
                continue
            delta = (_as_utc(tick.time) - now).total_seconds()
            if best is None or delta > best:
                best = delta

        if best is None or abs(best) / 60 > MAX_PLAUSIBLE_OFFSET_MINUTES:
            log.warning("mt5_server_offset_undetected", measured_seconds=best)
            return timedelta(0)

        offset = timedelta(minutes=_round_offset_minutes(best))
        log.info("mt5_server_offset_detected", hours=offset.total_seconds() / 3600)
        return offset

    def _server_to_utc(self, value) -> datetime:
        return _as_utc(value) - (self._server_offset or timedelta(0))

    def _utc_to_server(self, value: datetime) -> datetime:
        aware = value.astimezone(UTC) if value.tzinfo else value.replace(tzinfo=UTC)
        return aware + (self._server_offset or timedelta(0))

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
        self._server_offset = self._detect_server_offset()
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
            self._point_cache[info.name] = float(info.point)
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
                self._point_cache[match.name] = float(match.point)
                return match
        if ranked:
            ranked.sort(key=lambda s: len(s.name))
            self._mt5.symbol_select(ranked[0].name, True)
            self._point_cache[ranked[0].name] = float(ranked[0].point)
            return ranked[0]
        return None

    def copy_rates_range(self, symbol: str, timeframe: str, date_from: datetime, date_to: datetime) -> list[CandleRecord]:
        self._require()
        tf = TIMEFRAME_MT5[timeframe]
        # Bounds must be expressed on the server clock or the newest bars fall
        # outside the window by the server offset.
        start = self._utc_to_server(date_from)
        end = self._utc_to_server(date_to)
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
            timestamp=self._server_to_utc(tick.time),
            bid=float(tick.bid),
            ask=float(tick.ask),
            last=float(tick.last or tick.bid),
            volume=int(getattr(tick, "volume", 0) or 0),
        )

    def _to_candle(self, symbol: str, timeframe: str, row, tick: TickRecord | None) -> CandleRecord:
        spread = None
        bid = tick.bid if tick else None
        ask = tick.ask if tick else None
        # MT5 rate rows contain the spread observed for that historical bar in
        # integer symbol points. Never stamp today's tick spread onto history.
        names = getattr(getattr(row, "dtype", None), "names", None) or ()
        historical_points = row["spread"] if "spread" in names else None
        point = self._point_cache.get(symbol)
        if point is None:
            info = self._mt5.symbol_info(symbol)
            point = float(getattr(info, "point", 0) or 0)
            if point:
                self._point_cache[symbol] = point
        if historical_points is not None and point:
            spread = float(historical_points) * point
        elif bid is not None and ask is not None:
            spread = ask - bid
        return CandleRecord(
            symbol=symbol,
            timeframe=timeframe,
            timestamp=self._server_to_utc(row["time"]),
            open=float(row["open"]),
            high=float(row["high"]),
            low=float(row["low"]),
            close=float(row["close"]),
            tick_volume=int(row["tick_volume"]),
            real_volume=int(row["real_volume"]) if "real_volume" in names else 0,
            spread=spread,
            bid=bid,
            ask=ask,
        )

    def _require(self) -> None:
        if not self._connected or self._mt5 is None:
            raise RuntimeError(self._error or "MT5 is not connected")
