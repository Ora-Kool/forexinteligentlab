from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.constants import TIMEFRAME_MINUTES, pip_size_for
from app.core.logging import get_logger
from app.core.tenant import SYSTEM_WORKSPACE_ID, set_workspace_id
from app.models.collection import CollectionStatus
from app.models.instrument import MonitoredInstrument
from app.mt5.base import MT5Connector
from app.services.candles import candle_count, upsert_candles
from app.services.events import raise_alert, record_event
from app.services.features import persist_latest_features
from app.services.hub import hub
from app.services.predictions import generate_prediction, resolve_outcomes
from app.services.runtime import runtime

log = get_logger(__name__)


def _status_row(db: Session, symbol: str, timeframe: str) -> CollectionStatus:
    row = (
        db.query(CollectionStatus)
        .filter(
            CollectionStatus.workspace_id == SYSTEM_WORKSPACE_ID,
            CollectionStatus.symbol == symbol,
            CollectionStatus.timeframe == timeframe,
        )
        .one_or_none()
    )
    if row is None:
        row = CollectionStatus(
            workspace_id=SYSTEM_WORKSPACE_ID,
            symbol=symbol,
            timeframe=timeframe,
            collection_rate=f"1/{TIMEFRAME_MINUTES[timeframe]} min",
            status="IDLE",
        )
        db.add(row)
        db.commit()
        db.refresh(row)
    return row


def collect_once(db: Session, connector: MT5Connector) -> dict:
    set_workspace_id(SYSTEM_WORKSPACE_ID)
    settings = get_settings()
    status = connector.status()
    if not status.connected:
        try:
            status = connector.connect()
        except Exception as exc:
            runtime.mt5_connected = False
            runtime.mt5_error = str(exc)
            raise_alert(db, "mt5_disconnected", f"MT5 connection failed: {exc}")
            return {"ok": False, "error": str(exc)}

    if not status.connected:
        runtime.mt5_connected = False
        runtime.mt5_error = status.last_error or "MT5 is not connected"
        raise_alert(db, "mt5_disconnected", runtime.mt5_error)
        hub.publish("collector", {"type": "mt5", "status": "DISCONNECTED", "error": runtime.mt5_error})
        return {"ok": False, "error": runtime.mt5_error}

    runtime.mt5_connected = True
    runtime.mt5_error = ""
    runtime.mt5_mode = status.mode

    instruments = (
        db.query(MonitoredInstrument)
        .filter(
            MonitoredInstrument.workspace_id == SYSTEM_WORKSPACE_ID,
            MonitoredInstrument.enabled.is_(True),
        )
        .all()
    )
    results = []
    for instrument in instruments:
        row = _status_row(db, instrument.symbol, instrument.timeframe)
        try:
            resolved = connector.resolve_symbol(instrument.symbol)
            if resolved is None:
                raise ValueError(f"Symbol {instrument.symbol} does not exist on this MT5/FBS account")
            if resolved.name != instrument.symbol:
                instrument.symbol = resolved.name
                db.commit()

            candles = connector.copy_rates_from_pos(resolved.name, instrument.timeframe, 0, 8)
            if not candles:
                raise ValueError(f"No candles returned for {resolved.name} {instrument.timeframe}")
            stored = upsert_candles(db, candles)
            latest = candles[-1]
            tick = connector.symbol_tick(resolved.name)
            persist_latest_features(db, resolved.name, instrument.timeframe)
            prediction = generate_prediction(db, resolved.name, instrument.timeframe)
            resolve_outcomes(db, resolved.name, instrument.timeframe)

            row.last_candle = latest.timestamp
            row.candles_collected = candle_count(db, resolved.name, instrument.timeframe)
            row.status = "LIVE"
            row.last_error = ""
            row.updated_at = datetime.now(UTC)
            db.commit()

            runtime.last_data_at = datetime.now(UTC)
            spread_pips = None
            if latest.spread is not None:
                spread_pips = latest.spread / pip_size_for(resolved.name)
            if tick and tick.ask and tick.bid:
                spread_pips = (tick.ask - tick.bid) / pip_size_for(resolved.name)
            if spread_pips is not None and spread_pips >= settings.large_spread_pips:
                raise_alert(
                    db,
                    "large_spread",
                    f"{resolved.name} spread {spread_pips:.1f} pips exceeds threshold",
                    symbol=resolved.name,
                    timeframe=instrument.timeframe,
                )

            card = {
                "symbol": resolved.name,
                "timeframe": instrument.timeframe,
                "price": latest.close,
                "bid": tick.bid if tick else latest.bid,
                "ask": tick.ask if tick else latest.ask,
                "spread": latest.spread,
                "spread_pips": spread_pips,
                "timestamp": latest.timestamp,
                "status": "LIVE",
                "prediction": None
                if prediction is None
                else {
                    "probability_up": prediction.probability_up,
                    "probability_down": prediction.probability_down,
                    "prediction": prediction.prediction,
                    "model_version": prediction.model_version,
                    "timestamp": prediction.timestamp,
                },
            }
            runtime.last_tick[f"{resolved.name}:{instrument.timeframe}"] = card
            hub.publish("market", {"type": "candle", **card})
            if prediction is not None:
                hub.publish(
                    "predictions",
                    {
                        "type": "prediction",
                        "symbol": resolved.name,
                        "timeframe": instrument.timeframe,
                        "probability_up": prediction.probability_up,
                        "probability_down": prediction.probability_down,
                        "prediction": prediction.prediction,
                        "model_version": prediction.model_version,
                        "price": prediction.price,
                        "timestamp": prediction.timestamp,
                        "disclaimer": "Research prediction only. No order placed.",
                    },
                )
            results.append({"symbol": resolved.name, "inserted": stored["inserted"], "duplicates": stored["duplicates"]})
        except Exception as exc:
            log.error("collect_symbol_failed", symbol=instrument.symbol, error=str(exc))
            row.status = "ERROR"
            row.last_error = str(exc)
            row.updated_at = datetime.now(UTC)
            db.commit()
            record_event(db, "error", "collector", f"{instrument.symbol}: {exc}", {"symbol": instrument.symbol})
            results.append({"symbol": instrument.symbol, "error": str(exc)})

    hub.publish("collector", {"type": "status", **runtime.snapshot(), "results": results})
    return {"ok": True, "results": results}
