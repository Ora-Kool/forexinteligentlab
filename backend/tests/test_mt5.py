from datetime import UTC, datetime, timedelta

import pytest

from app.mt5.mock import MockMT5Connector


def test_mt5_connection_failure():
    connector = MockMT5Connector(fail_connect=True)
    status = connector.connect()
    assert status.connected is False
    assert "unavailable" in status.last_error.lower()
    with pytest.raises(RuntimeError):
        connector.discover_symbols()


def test_invalid_symbol():
    connector = MockMT5Connector()
    connector.connect()
    assert connector.resolve_symbol("NOTAREALPAIR") is None
    with pytest.raises(ValueError):
        connector.copy_rates_range("NOTAREALPAIR", "M5", datetime.now(UTC) - timedelta(hours=1), datetime.now(UTC))


def test_symbol_suffix_discovery():
    connector = MockMT5Connector()
    connector.connect()
    symbols = connector.discover_symbols("EURUSD")
    names = {item.name for item in symbols}
    assert "EURUSD" in names
    assert "EURUSD.a" in names
    assert "EURUSDm" in names
    resolved = connector.resolve_symbol("EURUSD")
    assert resolved is not None
    assert resolved.name == "EURUSD"


def test_copy_rates_are_utc():
    connector = MockMT5Connector()
    connector.connect()
    end = datetime.now(UTC)
    start = end - timedelta(hours=2)
    candles = connector.copy_rates_range("EURUSD", "M5", start, end)
    assert candles
    assert candles[0].timestamp.tzinfo is not None
    assert candles[0].open > 0
    assert candles[0].high >= candles[0].low
