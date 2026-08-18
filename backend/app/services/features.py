from datetime import UTC, datetime

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.ml.features import compute_feature_frame, latest_feature_dict
from app.models.candle import MarketCandle
from app.models.feature import FeatureRow
from app.services.candles import load_candles


def persist_latest_features(db: Session, symbol: str, timeframe: str, lookback: int = 120) -> dict | None:
    candles = load_candles(db, symbol, timeframe, limit=lookback)
    payload = latest_feature_dict(
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
        ]
    )
    if payload is None:
        return None
    ts = payload.get("candle_timestamp") or payload["timestamp"]
    stored = {k: v for k, v in payload.items() if k != "candle_timestamp"}
    row = FeatureRow(
        symbol=symbol,
        timeframe=timeframe,
        timestamp=ts,
        values=stored,
    )
    db.add(row)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        existing = (
            db.query(FeatureRow)
            .filter(
                FeatureRow.symbol == symbol,
                FeatureRow.timeframe == timeframe,
                FeatureRow.timestamp == ts,
            )
            .one()
        )
        existing.values = stored
        db.commit()
    return payload
