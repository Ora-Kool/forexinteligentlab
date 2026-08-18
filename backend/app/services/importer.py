from datetime import UTC, datetime

from sqlalchemy.orm import Session

from app.models.collection import CollectionJob
from app.mt5.base import MT5Connector
from app.services.candles import count_missing, upsert_candles
from app.services.events import record_event


def import_history(
    db: Session,
    connector: MT5Connector,
    symbol: str,
    timeframe: str,
    start: datetime,
    end: datetime,
) -> CollectionJob:
    job = CollectionJob(
        kind="historical_import",
        symbol=symbol,
        timeframe=timeframe,
        start_date=start,
        end_date=end,
        status="running",
    )
    db.add(job)
    db.commit()
    db.refresh(job)
    started = datetime.now(UTC)
    try:
        if not connector.status().connected:
            status = connector.connect()
            if not status.connected:
                raise RuntimeError(status.last_error or "MT5 is not connected")
        resolved = connector.resolve_symbol(symbol)
        if resolved is None:
            raise ValueError(f"Unknown symbol: {symbol}")
        job.symbol = resolved.name
        candles = connector.copy_rates_range(resolved.name, timeframe, start, end)
        stored = upsert_candles(db, candles)
        timestamps = [c.timestamp for c in candles]
        missing = count_missing(timestamps, timeframe, start, end) if timestamps else 0
        job.candles_requested = len(candles)
        job.candles_imported = stored["inserted"]
        job.duplicate_candles = stored["duplicates"]
        job.missing_candles = missing
        job.first_timestamp = stored["first_timestamp"]
        job.last_timestamp = stored["last_timestamp"]
        job.status = "error" if stored["errors"] else "completed"
        job.error = "; ".join(stored["errors"])
        record_event(
            db,
            "error" if stored["errors"] else "info",
            "import",
            f"Imported {stored['inserted']} {resolved.name} {timeframe} candles",
            {"duplicates": stored["duplicates"], "missing": missing, "errors": stored["errors"]},
        )
    except Exception as exc:
        job.status = "error"
        job.error = str(exc)
        record_event(db, "error", "import", f"Import failed: {exc}", {"symbol": symbol, "timeframe": timeframe})
    job.duration_seconds = (datetime.now(UTC) - started).total_seconds()
    job.finished_at = datetime.now(UTC)
    db.commit()
    db.refresh(job)
    return job
