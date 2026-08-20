from __future__ import annotations

import threading
from datetime import UTC, datetime

from app.core.config import get_settings
from app.core.constants import TIMEFRAME_MINUTES
from app.core.logging import get_logger
from app.core.tenant import SYSTEM_WORKSPACE_ID, set_workspace_id
from app.database.session import SessionLocal
from app.models.collection import CollectionStatus
from app.mt5.factory import get_connector
from app.services.collector import collect_once
from app.services.events import raise_alert, record_event
from app.services.hub import hub
from app.services.runtime import runtime

log = get_logger(__name__)


def _loop() -> None:
    set_workspace_id(SYSTEM_WORKSPACE_ID)
    settings = get_settings()
    connector = get_connector()
    record_event(SessionLocal(), "info", "collector", "Collector started")

    # One-shot history fill before live polling. Keeps FastAPI startup fast and
    # reuses the bridge/official adapter already owned by the collector thread.
    if settings.auto_backfill and not settings.is_agent_mode:
        db = SessionLocal()
        try:
            from app.services.backfill import backfill_monitored_history

            result = backfill_monitored_history(db, connector)
            log.info("auto_backfill_done", result=result)
        except Exception as exc:
            log.error("auto_backfill_failed", error=str(exc))
            try:
                record_event(db, "error", "backfill", f"Auto-backfill failed: {exc}")
            except Exception:
                pass
        finally:
            db.close()

    while not runtime.stop_event.is_set():
        set_workspace_id(SYSTEM_WORKSPACE_ID)
        db = SessionLocal()
        try:
            collect_once(db, connector)
            stale = (
                db.query(CollectionStatus)
                .filter(
                    CollectionStatus.workspace_id == SYSTEM_WORKSPACE_ID,
                    CollectionStatus.status == "LIVE",
                )
                .all()
            )
            now = datetime.now(UTC)
            for row in stale:
                if row.last_candle is None:
                    continue
                age = (now - row.last_candle.replace(tzinfo=row.last_candle.tzinfo or UTC)).total_seconds()
                # The newest bar is the one still forming, so its timestamp is up to
                # one full bar old on a healthy feed. Grace is added on top of that,
                # otherwise every timeframe above M5 reads STALE forever.
                allowed = TIMEFRAME_MINUTES.get(row.timeframe, 5) * 60 + settings.stale_candle_seconds
                if age > allowed:
                    row.status = "STALE"
                    db.commit()
                    raise_alert(
                        db,
                        "stale_candle",
                        f"No new candle for {row.symbol} {row.timeframe} in {int(age)}s "
                        f"(allowed {allowed}s)",
                        symbol=row.symbol,
                        timeframe=row.timeframe,
                    )
        except Exception as exc:
            log.error("collector_loop_error", error=str(exc))
            runtime.mt5_connected = False
            runtime.mt5_error = str(exc)
            try:
                record_event(db, "error", "collector", f"Collector loop error: {exc}")
            except Exception:
                pass
        finally:
            db.close()
        runtime.stop_event.wait(settings.collector_interval_seconds)

    runtime.collector_running = False
    try:
        record_event(SessionLocal(), "info", "collector", "Collector stopped")
    except Exception:
        pass
    hub.publish("collector", {"type": "status", **runtime.snapshot()})


def start_collector() -> dict:
    with runtime.lock:
        if runtime.collector_running:
            return {"status": "RUNNING", "message": "Collector already running"}
        runtime.stop_event.clear()
        runtime.collector_running = True
        thread = threading.Thread(target=_loop, name="fil-collector", daemon=True)
        runtime.collector_thread = thread
        thread.start()
        return {"status": "RUNNING", "message": "Collector started"}


def stop_collector() -> dict:
    runtime.stop_event.set()
    with runtime.lock:
        runtime.collector_running = False
    return {"status": "STOPPED", "message": "Collector stop requested"}
