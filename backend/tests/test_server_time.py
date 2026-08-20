"""MetaTrader reports times on the broker server clock, not UTC."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import numpy as np

from app.core.config import get_settings
from app.mt5.official import OfficialMT5Connector, _round_offset_minutes


class _Tick:
    def __init__(self, epoch: int) -> None:
        self.time = epoch
        self.bid = 1.1
        self.ask = 1.1001
        self.last = 1.1
        self.volume = 3


class _FakeMT5:
    """Minimal stand-in that stamps ticks three hours ahead of real UTC."""

    def __init__(self, offset_hours: float = 3.0) -> None:
        self.offset = timedelta(hours=offset_hours)
        self.range_calls: list[tuple[datetime, datetime]] = []

    def symbol_info_tick(self, symbol: str):
        server_now = datetime.now(UTC) + self.offset
        return _Tick(int(server_now.timestamp()))

    def copy_rates_range(self, symbol, tf, start, end):
        self.range_calls.append((start, end))
        return []


def _connector(offset_hours: float = 3.0) -> tuple[OfficialMT5Connector, _FakeMT5]:
    fake = _FakeMT5(offset_hours)
    connector = OfficialMT5Connector()
    connector._mt5 = fake
    connector._connected = True
    connector._server_offset = connector._detect_server_offset()
    return connector, fake


def test_round_offset_snaps_to_quarter_hours():
    assert _round_offset_minutes(10799) == 180
    assert _round_offset_minutes(7201) == 120
    assert _round_offset_minutes(0) == 0


def test_detects_positive_server_offset():
    connector, _ = _connector(3.0)
    assert connector._server_offset == timedelta(hours=3)


def test_candle_time_is_shifted_back_to_utc():
    connector, fake = _connector(3.0)
    server_now = datetime.now(UTC) + fake.offset
    converted = connector._server_to_utc(int(server_now.timestamp()))
    # Converted time must track real UTC, not the server's three-hour lead.
    assert abs((converted - datetime.now(UTC)).total_seconds()) < 5


def test_range_request_is_expressed_on_server_clock():
    connector, fake = _connector(3.0)
    start = datetime(2026, 8, 19, 0, 0, tzinfo=UTC)
    end = datetime(2026, 8, 19, 12, 0, tzinfo=UTC)
    connector.copy_rates_range("EURUSD", "M5", start, end)
    sent_start, sent_end = fake.range_calls[0]
    assert sent_start == start + timedelta(hours=3)
    assert sent_end == end + timedelta(hours=3)


def test_configured_offset_wins_over_detection(monkeypatch):
    monkeypatch.setenv("MT5_SERVER_UTC_OFFSET_MINUTES", "120")
    get_settings.cache_clear()
    try:
        connector, _ = _connector(3.0)
        assert connector._server_offset == timedelta(minutes=120)
    finally:
        monkeypatch.delenv("MT5_SERVER_UTC_OFFSET_MINUTES", raising=False)
        get_settings.cache_clear()


def test_stale_tick_offset_is_rejected():
    connector, _ = _connector(48.0)
    assert connector._server_offset == timedelta(0)


def test_historical_candle_uses_bar_spread_points_not_current_tick():
    connector, _ = _connector(3.0)
    connector._point_cache["EURUSD"] = 0.00001
    server_time = int((datetime.now(UTC) + timedelta(hours=3)).timestamp())
    row = np.array(
        [(server_time, 1.1, 1.2, 1.0, 1.15, 20, 123, 0)],
        dtype=[
            ("time", "i8"),
            ("open", "f8"),
            ("high", "f8"),
            ("low", "f8"),
            ("close", "f8"),
            ("spread", "i4"),
            ("tick_volume", "i8"),
            ("real_volume", "i8"),
        ],
    )[0]
    tick = _Tick(server_time)
    tick.bid = 1.10
    tick.ask = 1.11  # Current spread is 0.01; historical row was 0.00020.

    candle = connector._to_candle("EURUSD", "M5", row, tick)

    assert abs(candle.spread - 0.00020) < 1e-12
