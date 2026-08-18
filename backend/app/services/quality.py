from datetime import UTC, datetime, timedelta

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.core.constants import TIMEFRAME_MINUTES, pip_size_for
from app.models.candle import MarketCandle
from app.services.candles import count_missing


def quality_report(db: Session, symbol: str | None = None, timeframe: str | None = None) -> dict:
    query = db.query(MarketCandle)
    if symbol:
        query = query.filter(MarketCandle.symbol == symbol)
    if timeframe:
        query = query.filter(MarketCandle.timeframe == timeframe)
    rows = query.order_by(MarketCandle.timestamp.asc()).all()
    if not rows:
        return {
            "total_candles": 0,
            "missing_candles": 0,
            "duplicate_candles": 0,
            "latest_timestamp": None,
            "oldest_timestamp": None,
            "average_spread": None,
            "maximum_spread": None,
            "average_spread_pips": None,
            "maximum_spread_pips": None,
            "missing_intervals": [],
            "data_gaps": [],
            "availability": [],
        }

    timestamps = [row.timestamp for row in rows]
    spreads = [row.spread for row in rows if row.spread is not None]
    tf = timeframe or rows[0].timeframe
    minutes = TIMEFRAME_MINUTES.get(tf, 5)
    missing = count_missing(timestamps, tf, timestamps[0], timestamps[-1]) if timeframe else 0

    gaps = []
    for prev, curr in zip(timestamps, timestamps[1:]):
        delta = (curr - prev).total_seconds() / 60
        if delta > minutes * 1.5:
            gaps.append(
                {
                    "start": prev.isoformat(),
                    "end": curr.isoformat(),
                    "missing_bars": int(round(delta / minutes) - 1),
                }
            )

    pip = pip_size_for(symbol or rows[0].symbol)
    avg_spread = sum(spreads) / len(spreads) if spreads else None
    max_spread = max(spreads) if spreads else None

    # Daily availability timeline
    availability = []
    if timestamps:
        day = timestamps[0].astimezone(UTC).replace(hour=0, minute=0, second=0, microsecond=0)
        last_day = timestamps[-1].astimezone(UTC).replace(hour=0, minute=0, second=0, microsecond=0)
        by_day: dict[datetime, int] = {}
        for ts in timestamps:
            key = ts.astimezone(UTC).replace(hour=0, minute=0, second=0, microsecond=0)
            by_day[key] = by_day.get(key, 0) + 1
        expected_per_day = int(24 * 60 / minutes) if minutes else 1
        while day <= last_day:
            have = by_day.get(day, 0)
            availability.append(
                {
                    "date": day.date().isoformat(),
                    "candles": have,
                    "coverage": min(1.0, have / expected_per_day) if expected_per_day else 0,
                }
            )
            day += timedelta(days=1)

    return {
        "total_candles": len(rows),
        "missing_candles": missing,
        "duplicate_candles": 0,
        "latest_timestamp": timestamps[-1],
        "oldest_timestamp": timestamps[0],
        "average_spread": avg_spread,
        "maximum_spread": max_spread,
        "average_spread_pips": (avg_spread / pip) if avg_spread is not None else None,
        "maximum_spread_pips": (max_spread / pip) if max_spread is not None else None,
        "missing_intervals": gaps[:100],
        "data_gaps": gaps[:100],
        "availability": availability[-90:],
    }


def latest_timestamp(db: Session) -> datetime | None:
    value = db.query(func.max(MarketCandle.timestamp)).scalar()
    return value
