from datetime import UTC, datetime, timedelta

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.logging import get_logger
from app.core.tenant import SYSTEM_WORKSPACE_ID, set_workspace_id
from app.database import session as db_session
from app.database.session import Base
from app.models import *  # noqa: F401,F403
from app.mt5.factory import get_connector
from app.services.candles import upsert_candles
from app.services.events import record_event
from app.services.features import persist_latest_features
from app.services.runtime import runtime
from app.services.symbols import ensure_default_monitor, persist_discovered

log = get_logger(__name__)


def create_schema() -> None:
    Base.metadata.create_all(bind=db_session.engine)
    ensure_tenant_schema()


def ensure_tenant_schema() -> None:
    if db_session.engine.dialect.name != "postgresql":
        return
    statements = [
        "ALTER TABLE monitored_instruments ADD COLUMN IF NOT EXISTS workspace_id INTEGER NOT NULL DEFAULT 0",
        "ALTER TABLE collection_status ADD COLUMN IF NOT EXISTS workspace_id INTEGER NOT NULL DEFAULT 0",
        "ALTER TABLE collection_jobs ADD COLUMN IF NOT EXISTS workspace_id INTEGER NOT NULL DEFAULT 0",
        "ALTER TABLE model_versions ADD COLUMN IF NOT EXISTS workspace_id INTEGER NOT NULL DEFAULT 0",
        "ALTER TABLE model_predictions ADD COLUMN IF NOT EXISTS workspace_id INTEGER NOT NULL DEFAULT 0",
        "ALTER TABLE model_predictions ADD COLUMN IF NOT EXISTS exit_price DOUBLE PRECISION",
        "ALTER TABLE alerts ADD COLUMN IF NOT EXISTS workspace_id INTEGER NOT NULL DEFAULT 0",
        "ALTER TABLE system_events ADD COLUMN IF NOT EXISTS workspace_id INTEGER NOT NULL DEFAULT 0",
        "ALTER TABLE monitored_instruments DROP CONSTRAINT IF EXISTS uq_monitored_symbol_tf",
        "ALTER TABLE collection_status DROP CONSTRAINT IF EXISTS uq_status_symbol_tf",
        "ALTER TABLE model_versions DROP CONSTRAINT IF EXISTS model_versions_version_key",
        "CREATE UNIQUE INDEX IF NOT EXISTS uq_monitored_ws_symbol_tf ON monitored_instruments (workspace_id, symbol, timeframe)",
        "CREATE UNIQUE INDEX IF NOT EXISTS uq_status_ws_symbol_tf ON collection_status (workspace_id, symbol, timeframe)",
        "CREATE UNIQUE INDEX IF NOT EXISTS uq_model_ws_version ON model_versions (workspace_id, version)",
    ]
    with db_session.engine.begin() as connection:
        for statement in statements:
            connection.execute(text(statement))


def seed_if_needed(db: Session) -> None:
    set_workspace_id(SYSTEM_WORKSPACE_ID)
    settings = get_settings()
    try:
        connector = get_connector()
        status = connector.connect()
    except Exception as exc:
        runtime.mt5_connected = False
        runtime.mt5_error = str(exc)
        record_event(db, "error", "mt5", f"Startup MT5 connection failed: {exc}")
        return

    runtime.mt5_connected = status.connected
    runtime.mt5_error = status.last_error
    runtime.mt5_mode = status.mode
    if not status.connected:
        record_event(db, "error", "mt5", status.last_error or "MT5 unavailable at startup")
        return

    try:
        persist_discovered(db, connector.discover_symbols())
    except Exception as exc:
        db.rollback()
        record_event(db, "warning", "mt5", f"Symbol discovery skipped at startup: {exc}")

    try:
        instruments = ensure_default_monitor(db, connector)
    except Exception as exc:
        db.rollback()
        record_event(db, "error", "mt5", f"Default monitor bootstrap failed: {exc}")
        return

    from app.models.candle import MarketCandle

    existing = db.query(MarketCandle).count()
    if settings.app_env == "test" or not settings.is_mock:
        return

    if not existing:
        end = datetime.now(UTC)
        start = end - timedelta(days=settings.seed_history_days)
        for instrument in instruments:
            try:
                candles = connector.copy_rates_range(instrument.symbol, instrument.timeframe, start, end)
                upsert_candles(db, candles)
                persist_latest_features(db, instrument.symbol, instrument.timeframe, lookback=200)
            except Exception as exc:
                db.rollback()
                record_event(db, "error", "seed", f"Failed to seed {instrument.symbol}: {exc}")
        record_event(db, "info", "seed", f"Seeded mock history for {len(instruments)} instruments")

    from app.models.prediction import ModelVersion

    if db.query(ModelVersion).count() == 0:
        _train_seed_models(db, instruments)


def _train_seed_models(db: Session, instruments) -> None:
    from app.core.constants import RESEARCH_DISCLAIMER, pip_size_for
    from app.ml.train import train_logistic_regression
    from app.models.candle import MarketCandle
    from app.models.prediction import ModelVersion
    from app.services.predictions import generate_prediction

    settings = get_settings()
    for instrument in instruments:
        candles = [
            {
                "symbol": c.symbol,
                "timeframe": c.timeframe,
                "timestamp": c.timestamp,
                "open": c.open,
                "high": c.high,
                "low": c.low,
                "close": c.close,
                "spread": c.spread or 0.0,
            }
            for c in db.query(MarketCandle)
            .filter(MarketCandle.symbol == instrument.symbol, MarketCandle.timeframe == instrument.timeframe)
            .order_by(MarketCandle.timestamp.asc())
            .all()
        ]
        try:
            result = train_logistic_regression(
                candles,
                symbol=instrument.symbol,
                timeframe=instrument.timeframe,
                spread_cost_pips=settings.spread_cost_pips,
                transaction_cost_pips=settings.transaction_cost_pips,
                pip_size=pip_size_for(instrument.symbol),
            )
            version = ModelVersion(
                name=result["name"],
                version=f"{instrument.symbol}-{result['version']}",
                algorithm=result["algorithm"],
                symbol=result["symbol"],
                timeframe=result["timeframe"],
                feature_list=result["feature_list"],
                training_start=result["training_start"],
                training_end=result["training_end"],
                train_samples=result["train_samples"],
                validation_samples=result["validation_samples"],
                accuracy=result["classification"]["accuracy"],
                precision=result["classification"]["precision"],
                recall=result["classification"]["recall"],
                f1=result["classification"]["f1"],
                roc_auc=result["classification"]["roc_auc"],
                log_loss=result["classification"]["log_loss"],
                confusion_matrix=result["classification"]["confusion_matrix"],
                strategy_metrics=result["strategy"],
                artifact_path=result["artifact_path"],
                is_active=True,
                notes=RESEARCH_DISCLAIMER,
            )
            db.add(version)
            db.commit()
            generate_prediction(db, instrument.symbol, instrument.timeframe)
        except Exception as exc:
            db.rollback()
            record_event(db, "error", "training", f"Seed training failed for {instrument.symbol}: {exc}")


def initialize() -> None:
    create_schema()
    db = db_session.SessionLocal()
    try:
        db.execute(__import__("sqlalchemy").text("SELECT 1"))
        runtime.database_ok = True
        seed_if_needed(db)
    except Exception as exc:
        runtime.database_ok = False
        runtime.database_error = str(exc)
        log.error("database_init_failed", error=str(exc))
        raise
    finally:
        db.close()
