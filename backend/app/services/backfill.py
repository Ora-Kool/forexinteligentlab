"""Automatic historical backfill for monitored instruments.

Pulls SEED_HISTORY_DAYS of candles from the active MT5 adapter (bridge /
official / mock) whenever an instrument has too few bars. Safe to re-run:
upserts are idempotent and finished jobs leave a paper trail in collection_jobs.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.constants import TIMEFRAME_MINUTES
from app.core.logging import get_logger
from app.core.tenant import SYSTEM_WORKSPACE_ID, set_workspace_id
from app.mt5.base import MT5Connector
from app.services.candles import candle_count
from app.services.collector import monitored_pairs
from app.services.events import record_event
from app.services.features import persist_latest_features
from app.services.importer import import_history

log = get_logger(__name__)

# Comfortable margin over the trainer's 80-labeled-bar minimum, so a chronological
# 80/20 split still leaves a usable validation set.
TRAINING_BARS_TARGET = 600
MAX_BACKFILL_DAYS = 730
# Bars per import request; keeps Wine/bridge round-trips and MT5 limits healthy.
CHUNK_BARS = 500


def _expected_bars(timeframe: str, days: int) -> int:
    minutes = TIMEFRAME_MINUTES.get(timeframe, 5)
    # Forex is roughly 5 of 7 calendar days; leave headroom for gaps.
    return max(50, int(days * (1440 / minutes) * (5 / 7)))


def _days_for_bars(timeframe: str, bars: int) -> int:
    """Calendar days needed to collect ``bars`` closed candles of ``timeframe``."""
    minutes = TIMEFRAME_MINUTES.get(timeframe, 5)
    return max(1, int(bars * minutes / 1440 * (7 / 5)) + 1)


def needs_backfill(db: Session, symbol: str, timeframe: str, days: int) -> bool:
    have = candle_count(db, symbol, timeframe)
    want = _expected_bars(timeframe, days)
    if have < max(100, want // 2):
        return True

    # Also require the oldest bar to reach far enough back into the window.
    from app.models.candle import MarketCandle
    from sqlalchemy import func

    oldest = (
        db.query(func.min(MarketCandle.timestamp))
        .filter(MarketCandle.symbol == symbol, MarketCandle.timeframe == timeframe)
        .scalar()
    )
    if oldest is None:
        return True
    if oldest.tzinfo is None:
        oldest = oldest.replace(tzinfo=UTC)
    target_start = datetime.now(UTC) - timedelta(days=days)
    # Allow one day of slack for weekends / broker gaps.
    return oldest > target_start + timedelta(days=1)


def backfill_symbol_history(
    db: Session,
    connector: MT5Connector,
    symbol: str,
    timeframe: str,
    days: int,
) -> dict:
    """Import ``days`` of history for one symbol/timeframe in chunks.

    Chunks are sized by a bar budget rather than a fixed number of days: the
    binding constraint is bars per request, so a weekly chunk that is right for
    M5 would cost ~100 near-empty round-trips on D1.
    """
    end = datetime.now(UTC)
    cursor = end - timedelta(days=days)
    chunk_days = min(max(_days_for_bars(timeframe, CHUNK_BARS), 7), 180)
    imported_total = 0
    last_status = "completed"
    last_error = ""

    while cursor < end:
        chunk_end = min(cursor + timedelta(days=chunk_days), end)
        job = import_history(db, connector, symbol, timeframe, cursor, chunk_end)
        imported_total += int(job.candles_imported or 0)
        last_status = job.status
        last_error = job.error or ""
        if job.status == "error":
            break
        cursor = chunk_end

    try:
        persist_latest_features(db, symbol, timeframe, lookback=300)
    except Exception as exc:
        db.rollback()
        record_event(db, "warning", "backfill", f"Feature refresh failed for {symbol}: {exc}")

    log.info(
        "backfill_instrument",
        symbol=symbol,
        timeframe=timeframe,
        status=last_status,
        candles_imported=imported_total,
    )
    return {
        "symbol": symbol,
        "timeframe": timeframe,
        "status": last_status,
        "candles_imported": imported_total,
        "error": last_error,
    }


def ensure_history_for_training(
    db: Session,
    connector: MT5Connector,
    symbol: str,
    timeframe: str,
) -> dict | None:
    """Fill history on demand so training a fresh timeframe just works.

    Returns the backfill result, or ``None`` when no import was attempted.
    """
    settings = get_settings()
    if settings.app_env == "test" or not settings.auto_backfill or settings.is_agent_mode:
        return None

    # SEED_HISTORY_DAYS is tuned for M5. On H4/D1 the same window yields barely
    # more bars than the trainer's 80-sample floor, so widen it per timeframe.
    days = max(int(settings.seed_history_days), _days_for_bars(timeframe, TRAINING_BARS_TARGET))
    days = min(days, MAX_BACKFILL_DAYS)
    if not needs_backfill(db, symbol, timeframe, days):
        return None

    record_event(
        db,
        "info",
        "backfill",
        f"Training requested {symbol} {timeframe} with thin history; importing {days}d",
    )
    return backfill_symbol_history(db, connector, symbol, timeframe, days)


def backfill_monitored_history(db: Session, connector: MT5Connector) -> dict:
    """Import missing history for every enabled monitored instrument."""
    set_workspace_id(SYSTEM_WORKSPACE_ID)
    settings = get_settings()
    if settings.app_env == "test" or not settings.auto_backfill:
        return {"skipped": True, "reason": "disabled", "jobs": []}
    if settings.is_agent_mode:
        return {"skipped": True, "reason": "agent_mode", "jobs": []}

    days = max(1, int(settings.seed_history_days))
    # Union across workspaces: candles are shared, so seed whatever anyone watches.
    instruments = monitored_pairs(db)
    if not instruments:
        return {"skipped": True, "reason": "no_instruments", "jobs": []}

    jobs: list[dict] = []

    record_event(
        db,
        "info",
        "backfill",
        f"Auto-backfill checking {len(instruments)} instruments for {days}d history",
    )

    for symbol, timeframe, _workspace_ids in instruments:
        # Same per-timeframe widening as on-demand training fills.
        window = min(max(days, _days_for_bars(timeframe, TRAINING_BARS_TARGET)), MAX_BACKFILL_DAYS)
        if not needs_backfill(db, symbol, timeframe, window):
            jobs.append({"symbol": symbol, "timeframe": timeframe, "status": "skipped", "reason": "enough_history"})
            continue

        jobs.append(backfill_symbol_history(db, connector, symbol, timeframe, window))

    record_event(
        db,
        "info",
        "backfill",
        f"Auto-backfill finished for {len(instruments)} instruments",
        {"jobs": jobs},
    )
    return {"skipped": False, "days": days, "jobs": jobs}
