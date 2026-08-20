"""Auto-backfill decides when monitored instruments need history."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from app.models.candle import MarketCandle
from app.services.backfill import _expected_bars, needs_backfill

# Unique to this module: other suites write EURUSD M5 bars into the shared session.
SYMBOL = "BKFILL"


def test_expected_bars_scales_with_timeframe():
    m5 = _expected_bars("M5", 14)
    h1 = _expected_bars("H1", 14)
    assert m5 > h1
    assert m5 >= 100


def test_needs_backfill_when_thin(db_session):
    assert needs_backfill(db_session, SYMBOL, "M5", 14) is True

    now = datetime.now(UTC)
    db_session.add_all(
        [
            MarketCandle(
                symbol=SYMBOL,
                timeframe="M5",
                timestamp=now - timedelta(minutes=5 * i),
                open=1.0,
                high=1.0,
                low=1.0,
                close=1.0,
            )
            for i in range(2500)
        ]
    )
    db_session.commit()
    # Oldest bar is only ~8.7 days back, so a 14d window still needs fill.
    assert needs_backfill(db_session, SYMBOL, "M5", 14) is True

    db_session.add_all(
        [
            MarketCandle(
                symbol=SYMBOL,
                timeframe="M5",
                timestamp=now - timedelta(days=14, minutes=5 * i),
                open=1.0,
                high=1.0,
                low=1.0,
                close=1.0,
            )
            for i in range(10)
        ]
    )
    db_session.commit()
    assert needs_backfill(db_session, SYMBOL, "M5", 14) is False
