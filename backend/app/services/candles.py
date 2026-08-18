from datetime import UTC, datetime, timedelta

from sqlalchemy import func
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.orm import Session

from app.core.constants import TIMEFRAME_MINUTES
from app.models.candle import MarketCandle
from app.mt5.base import CandleRecord


def candle_to_dict(record: MarketCandle) -> dict:
    return {
        "id": record.id,
        "symbol": record.symbol,
        "timeframe": record.timeframe,
        "timestamp": record.timestamp,
        "open": record.open,
        "high": record.high,
        "low": record.low,
        "close": record.close,
        "bid": record.bid,
        "ask": record.ask,
        "spread": record.spread,
        "tick_volume": record.tick_volume,
        "real_volume": record.real_volume,
        "created_at": record.created_at,
    }


def upsert_candles(db: Session, records: list[CandleRecord]) -> dict:
    if not records:
        return {"inserted": 0, "duplicates": 0, "errors": [], "first_timestamp": None, "last_timestamp": None}

    rows = []
    first_ts = None
    last_ts = None
    for item in records:
        ts = item.timestamp.astimezone(UTC) if item.timestamp.tzinfo else item.timestamp.replace(tzinfo=UTC)
        first_ts = ts if first_ts is None else min(first_ts, ts)
        last_ts = ts if last_ts is None else max(last_ts, ts)
        rows.append(
            {
                "symbol": item.symbol,
                "timeframe": item.timeframe,
                "timestamp": ts,
                "open": item.open,
                "high": item.high,
                "low": item.low,
                "close": item.close,
                "bid": item.bid,
                "ask": item.ask,
                "spread": item.spread,
                "tick_volume": item.tick_volume,
                "real_volume": item.real_volume,
                "created_at": datetime.now(UTC),
            }
        )

    dialect = db.get_bind().dialect.name
    insert_fn = sqlite_insert if dialect == "sqlite" else pg_insert
    statement = insert_fn(MarketCandle).values(rows)
    statement = statement.on_conflict_do_nothing(index_elements=["symbol", "timeframe", "timestamp"])
    errors: list[str] = []
    try:
        before = db.query(func.count(MarketCandle.id)).scalar() or 0
        db.execute(statement)
        db.commit()
        after = db.query(func.count(MarketCandle.id)).scalar() or 0
    except Exception as exc:
        db.rollback()
        errors.append(str(exc))
        return {
            "inserted": 0,
            "duplicates": 0,
            "errors": errors,
            "first_timestamp": first_ts,
            "last_timestamp": last_ts,
        }
    inserted = int(after - before)
    return {
        "inserted": inserted,
        "duplicates": max(0, len(rows) - inserted),
        "errors": errors,
        "first_timestamp": first_ts,
        "last_timestamp": last_ts,
    }


def count_missing(timestamps: list[datetime], timeframe: str, start: datetime, end: datetime) -> int:
    if not timestamps:
        return 0
    minutes = TIMEFRAME_MINUTES[timeframe]
    expected = set()
    cursor = start.astimezone(UTC)
    end = end.astimezone(UTC)
    # Align to timeframe
    remainder = cursor.minute % minutes
    if remainder:
        cursor += timedelta(minutes=minutes - remainder)
    cursor = cursor.replace(second=0, microsecond=0)
    while cursor <= end:
        expected.add(cursor.replace(second=0, microsecond=0))
        cursor += timedelta(minutes=minutes)
    have = {ts.astimezone(UTC).replace(second=0, microsecond=0) for ts in timestamps}
    return len(expected - have)


def load_candles(db: Session, symbol: str, timeframe: str, limit: int = 500, start=None, end=None) -> list[MarketCandle]:
    query = db.query(MarketCandle).filter(MarketCandle.symbol == symbol, MarketCandle.timeframe == timeframe)
    if start is not None:
        query = query.filter(MarketCandle.timestamp >= start)
    if end is not None:
        query = query.filter(MarketCandle.timestamp <= end)
    return list(query.order_by(MarketCandle.timestamp.desc()).limit(limit).all())[::-1]


def candle_count(db: Session, symbol: str | None = None, timeframe: str | None = None) -> int:
    query = db.query(func.count(MarketCandle.id))
    if symbol:
        query = query.filter(MarketCandle.symbol == symbol)
    if timeframe:
        query = query.filter(MarketCandle.timeframe == timeframe)
    return int(query.scalar() or 0)
