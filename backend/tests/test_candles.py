from datetime import UTC, datetime, timedelta

from app.mt5.base import CandleRecord
from app.services.candles import count_missing, upsert_candles


def _candle(ts: datetime, symbol="EURUSD", close=1.1) -> CandleRecord:
    return CandleRecord(
        symbol=symbol,
        timeframe="M5",
        timestamp=ts,
        open=close,
        high=close + 0.0002,
        low=close - 0.0002,
        close=close,
        spread=0.00008,
        tick_volume=10,
    )


def test_duplicate_candle_rejected(db_session):
    ts = datetime(2024, 1, 2, 10, 0, tzinfo=UTC)
    first = upsert_candles(db_session, [_candle(ts)])
    second = upsert_candles(db_session, [_candle(ts, close=1.2)])
    assert first["inserted"] == 1
    assert second["inserted"] == 0
    assert second["duplicates"] == 1


def test_missing_candle_detection():
    start = datetime(2024, 1, 2, 10, 0, tzinfo=UTC)
    timestamps = [start, start + timedelta(minutes=5), start + timedelta(minutes=15)]
    missing = count_missing(timestamps, "M5", start, start + timedelta(minutes=15))
    assert missing == 1


def test_database_failure_is_visible(db_session, monkeypatch):
    def boom(*_args, **_kwargs):
        raise RuntimeError("database is down")

    monkeypatch.setattr(db_session, "execute", boom)
    result = upsert_candles(db_session, [_candle(datetime(2024, 1, 2, 11, 0, tzinfo=UTC))])
    assert result["inserted"] == 0
    assert result["errors"]
    assert "database is down" in result["errors"][0]
