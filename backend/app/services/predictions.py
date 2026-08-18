from datetime import UTC, datetime

from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.tenant import SYSTEM_WORKSPACE_ID, current_workspace_id
from app.ml.predict import predict_from_candles
from app.models.prediction import ModelPrediction, ModelVersion
from app.services.candles import load_candles
from app.services.events import raise_alert


def active_model(db: Session, symbol: str, timeframe: str) -> ModelVersion | None:
    workspace_id = current_workspace_id()
    own = (
        db.query(ModelVersion)
        .filter(
            ModelVersion.workspace_id == workspace_id,
            ModelVersion.symbol == symbol,
            ModelVersion.timeframe == timeframe,
            ModelVersion.is_active.is_(True),
        )
        .order_by(ModelVersion.created_at.desc())
        .first()
    )
    if own or workspace_id == SYSTEM_WORKSPACE_ID:
        return own
    return (
        db.query(ModelVersion)
        .filter(
            ModelVersion.workspace_id == SYSTEM_WORKSPACE_ID,
            ModelVersion.symbol == symbol,
            ModelVersion.timeframe == timeframe,
            ModelVersion.is_active.is_(True),
        )
        .order_by(ModelVersion.created_at.desc())
        .first()
    )


def generate_prediction(db: Session, symbol: str, timeframe: str) -> ModelPrediction | None:
    model = active_model(db, symbol, timeframe)
    if model is None or not model.artifact_path:
        return None
    candles = load_candles(db, symbol, timeframe, limit=200)
    payload = predict_from_candles(
        model.artifact_path,
        [
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
            for c in candles
        ],
    )
    if payload is None:
        return None
    existing = (
        db.query(ModelPrediction)
        .filter(
            ModelPrediction.workspace_id == current_workspace_id(),
            ModelPrediction.symbol == symbol,
            ModelPrediction.timeframe == timeframe,
            ModelPrediction.timestamp == payload["candle_timestamp"],
            ModelPrediction.model_version == payload["model_version"],
        )
        .first()
    )
    if existing:
        return existing
    row = ModelPrediction(
        model_version_id=model.id,
        model_version=payload["model_version"],
        symbol=symbol,
        timeframe=timeframe,
        timestamp=payload["candle_timestamp"],
        price=payload["price"],
        probability_up=payload["probability_up"],
        probability_down=payload["probability_down"],
        prediction=payload["prediction"],
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    settings = get_settings()
    if row.probability_up >= settings.alert_probability_threshold:
        raise_alert(
            db,
            "high_probability",
            f"{symbol} {timeframe} Probability UP: {row.probability_up:.0%} (research only, no order placed)",
            symbol=symbol,
            timeframe=timeframe,
        )
    return row


def resolve_outcomes(db: Session, symbol: str, timeframe: str) -> int:
    pending = (
        db.query(ModelPrediction)
        .filter(
            ModelPrediction.workspace_id == current_workspace_id(),
            ModelPrediction.symbol == symbol,
            ModelPrediction.timeframe == timeframe,
            ModelPrediction.actual_outcome.is_(None),
        )
        .all()
    )
    updated = 0
    from app.models.candle import MarketCandle

    for pred in pending:
        nxt = (
            db.query(MarketCandle)
            .filter(
                MarketCandle.symbol == symbol,
                MarketCandle.timeframe == timeframe,
                MarketCandle.timestamp > pred.timestamp,
            )
            .order_by(MarketCandle.timestamp.asc())
            .first()
        )
        if nxt is None:
            continue
        actual = 1 if nxt.close > pred.price else 0
        pred.actual_outcome = actual
        pred.exit_price = float(nxt.close)
        pred.correct = (pred.prediction == "UP" and actual == 1) or (pred.prediction == "DOWN" and actual == 0)
        updated += 1
    if updated:
        db.commit()
    return updated
