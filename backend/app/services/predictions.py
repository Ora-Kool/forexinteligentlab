from datetime import UTC, datetime
from pathlib import Path

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.constants import RESEARCH_DISCLAIMER, pip_size_for
from app.core.tenant import SYSTEM_WORKSPACE_ID, current_workspace_id
from app.ml.predict import predict_from_candles
from app.models.candle import MarketCandle
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


def research_pips(pred: ModelPrediction) -> float | None:
    """Signed next-bar pips if the call had been followed (long UP / short DOWN).

    This is a paper score, not a filled trade. Spread and commissions are
    applied separately by the summary so gross profit and loss stay visible.
    """
    if pred.exit_price is None or pred.price is None:
        return None
    size = pip_size_for(pred.symbol)
    if not size:
        return None
    move = float(pred.exit_price) - float(pred.price)
    signed = move if pred.prediction == "UP" else -move
    return round(signed / size, 2)


def summarize_predictions(preds: list[ModelPrediction], cost_pips: float) -> dict:
    profits: list[float] = []
    losses: list[float] = []
    scratches = 0
    hits = 0
    misses = 0
    pending = 0
    for pred in preds:
        pips = research_pips(pred)
        if pips is None:
            pending += 1
            continue
        if pred.correct:
            hits += 1
        else:
            misses += 1
        if pips > 0:
            profits.append(pips)
        elif pips < 0:
            losses.append(pips)
        else:
            scratches += 1

    profit_pips = sum(profits)
    loss_pips = sum(losses)
    resolved = len(preds) - pending
    return {
        "predictions": len(preds),
        "resolved": resolved,
        "pending": pending,
        "hits": hits,
        "misses": misses,
        "scratch_count": scratches,
        "profit": {
            "count": len(profits),
            "pips": round(profit_pips, 2),
            "avg_pips": round(profit_pips / len(profits), 2) if profits else 0.0,
        },
        "loss": {
            "count": len(losses),
            "pips": round(loss_pips, 2),
            "avg_pips": round(loss_pips / len(losses), 2) if losses else 0.0,
        },
        "net_pips": round(profit_pips + loss_pips, 2),
        "cost_pips_per_call": cost_pips,
        "net_pips_after_cost": round(profit_pips + loss_pips - cost_pips * resolved, 2) if resolved else 0.0,
        "disclaimer": RESEARCH_DISCLAIMER,
    }


def market_coverage(db: Session) -> dict:
    candles = int(db.query(func.count(MarketCandle.id)).scalar() or 0)
    symbols = int(db.query(func.count(func.distinct(MarketCandle.symbol))).scalar() or 0)
    series = len(db.query(MarketCandle.symbol, MarketCandle.timeframe).distinct().all())
    oldest = db.query(func.min(MarketCandle.timestamp)).scalar()
    newest = db.query(func.max(MarketCandle.timestamp)).scalar()
    return {
        "candles": candles,
        "symbols": symbols,
        "series": series,
        "oldest": oldest,
        "newest": newest,
    }


def _unlink_artifact(path: str) -> bool:
    if not path:
        return False
    file = Path(path)
    if not file.is_file():
        return False
    file.unlink()
    return True


def delete_model_version(db: Session, model_id: int) -> dict:
    """Remove a model this workspace owns. Predictions stay; the FK is cleared.

    If the deleted row was active, the newest remaining sibling for that
    symbol/timeframe is promoted so the collector keeps scoring.
    """
    workspace_id = current_workspace_id()
    model = (
        db.query(ModelVersion)
        .filter(ModelVersion.id == model_id, ModelVersion.workspace_id == workspace_id)
        .one_or_none()
    )
    if model is None:
        return {"ok": False, "reason": "not_found"}

    promoted_id = None
    if model.is_active:
        sibling = (
            db.query(ModelVersion)
            .filter(
                ModelVersion.workspace_id == workspace_id,
                ModelVersion.symbol == model.symbol,
                ModelVersion.timeframe == model.timeframe,
                ModelVersion.id != model.id,
            )
            .order_by(ModelVersion.created_at.desc())
            .first()
        )
        if sibling is not None:
            sibling.is_active = True
            promoted_id = sibling.id

    db.query(ModelPrediction).filter(ModelPrediction.model_version_id == model.id).update(
        {"model_version_id": None}
    )

    artifact = model.artifact_path
    payload = {
        "ok": True,
        "id": model.id,
        "version": model.version,
        "symbol": model.symbol,
        "timeframe": model.timeframe,
        "promoted_id": promoted_id,
        "artifact_removed": False,
    }
    db.delete(model)
    db.flush()

    still_used = (
        db.query(ModelVersion.id).filter(ModelVersion.artifact_path == artifact).first() if artifact else True
    )
    if artifact and still_used is None:
        payload["artifact_removed"] = _unlink_artifact(artifact)

    db.commit()
    return payload


def prune_inactive_models(db: Session) -> dict:
    """Delete every inactive model this workspace owns."""
    workspace_id = current_workspace_id()
    ids = [
        row.id
        for row in db.query(ModelVersion)
        .filter(ModelVersion.workspace_id == workspace_id, ModelVersion.is_active.is_(False))
        .all()
    ]
    deleted = []
    for model_id in ids:
        result = delete_model_version(db, model_id)
        if result.get("ok"):
            deleted.append(result)
    return {"ok": True, "deleted": len(deleted), "versions": deleted}
