from __future__ import annotations

import hashlib
from datetime import UTC, datetime

from sqlalchemy.orm import Session

from app.core.constants import pip_size_for
from app.core.tenant import current_workspace_id
from app.ml.metrics import json_safe
from app.models.candle import MarketCandle
from app.models.research import ResearchExperiment, ResearchFold
from app.research.config import ResearchConfig
from app.research.evaluator import run_walk_forward_experiment
from app.research.targets import build_triple_barrier_table


def _candle_payload(row: MarketCandle) -> dict:
    return {
        "symbol": row.symbol,
        "timeframe": row.timeframe,
        "timestamp": row.timestamp,
        "open": row.open,
        "high": row.high,
        "low": row.low,
        "close": row.close,
        "spread": row.spread or 0.0,
        "tick_volume": row.tick_volume,
    }


def dataset_version(candles: list[dict]) -> str:
    digest = hashlib.sha256()
    for row in candles:
        digest.update(
            "|".join(
                [
                    row["timestamp"].isoformat(),
                    f"{float(row['open']):.10f}",
                    f"{float(row['high']):.10f}",
                    f"{float(row['low']):.10f}",
                    f"{float(row['close']):.10f}",
                    f"{float(row['spread']):.10f}",
                ]
            ).encode()
        )
    return f"sha256:{digest.hexdigest()[:20]}:{len(candles)}"


def create_and_run_experiment(
    db: Session,
    *,
    symbol: str,
    timeframe: str,
    config: ResearchConfig,
    strategy_name: str = "Triple barrier logistic",
) -> ResearchExperiment:
    config.validate()
    rows = (
        db.query(MarketCandle)
        .filter(MarketCandle.symbol == symbol, MarketCandle.timeframe == timeframe)
        .order_by(MarketCandle.timestamp.asc())
        .all()
    )
    candles = [_candle_payload(row) for row in rows]
    if not candles:
        raise ValueError(f"No candles available for {symbol} {timeframe}.")

    now = datetime.now(UTC)
    code = f"TB-{symbol}-{timeframe}-{now.strftime('%Y%m%dT%H%M%S%fZ')}"
    experiment = ResearchExperiment(
        workspace_id=current_workspace_id(),
        code=code,
        strategy_name=strategy_name,
        symbol=symbol,
        timeframe=timeframe,
        target_version="triple_barrier_v1",
        feature_version="causal_features_v1",
        evaluator_version="purged_walk_forward_v1",
        model_family="LogisticRegression",
        dataset_version=dataset_version(candles),
        status="RUNNING",
        parameters=config.to_dict(),
        train_start=rows[0].timestamp,
        train_end=rows[-1].timestamp,
    )
    db.add(experiment)
    db.commit()
    db.refresh(experiment)

    try:
        table = build_triple_barrier_table(candles, config, pip_size_for(symbol))
        result = run_walk_forward_experiment(table, config)
        metrics = json_safe(result["metrics"])
        metrics["target_rows"] = int(len(table))
        metrics["source_candles"] = len(candles)
        metrics["methodology"] = result["methodology"]
        metrics["recent_signals"] = json_safe(result["signals"])
        experiment.metrics = metrics
        experiment.status = metrics.get("status") or "COMPLETED"
        experiment.finished_at = datetime.now(UTC)

        for payload in result["folds"]:
            db.add(
                ResearchFold(
                    experiment_id=experiment.id,
                    fold_index=payload["fold_index"],
                    train_start=payload["train_start"],
                    train_end=payload["train_end"],
                    validation_start=payload["validation_start"],
                    validation_end=payload["validation_end"],
                    threshold=payload["threshold"],
                    train_samples=payload["train_samples"],
                    validation_samples=payload["validation_samples"],
                    signals=payload["signals"],
                    metrics=json_safe(
                        {
                            **payload["metrics"],
                            "tuning": payload["tuning_metrics"],
                        }
                    ),
                )
            )
        db.commit()
        db.refresh(experiment)
        return experiment
    except Exception as exc:
        db.rollback()
        experiment = db.query(ResearchExperiment).filter(ResearchExperiment.id == experiment.id).one()
        experiment.status = "FAILED"
        experiment.error = str(exc)
        experiment.finished_at = datetime.now(UTC)
        db.commit()
        raise
