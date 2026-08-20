from __future__ import annotations

import math
from datetime import date, datetime

import numpy as np
from sklearn.metrics import (
    accuracy_score,
    confusion_matrix,
    f1_score,
    log_loss,
    precision_score,
    recall_score,
    roc_auc_score,
)


def json_safe(value):
    """Convert NaN/Inf to None so PostgreSQL JSONB accepts the payload."""
    if isinstance(value, dict):
        return {k: json_safe(v) for k, v in value.items()}
    if isinstance(value, list):
        return [json_safe(v) for v in value]
    if isinstance(value, tuple):
        return [json_safe(v) for v in value]
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, (float, np.floating)):
        number = float(value)
        if math.isnan(number) or math.isinf(number):
            return None
        return number
    if isinstance(value, (np.integer,)):
        return int(value)
    return value


def classification_metrics(y_true, y_prob) -> dict:
    y_true = np.asarray(y_true).astype(int)
    y_prob = np.asarray(y_prob).astype(float)
    y_pred = (y_prob >= 0.5).astype(int)
    metrics = {
        "accuracy": float(accuracy_score(y_true, y_pred)) if len(y_true) else None,
        "precision": float(precision_score(y_true, y_pred, zero_division=0)) if len(y_true) else None,
        "recall": float(recall_score(y_true, y_pred, zero_division=0)) if len(y_true) else None,
        "f1": float(f1_score(y_true, y_pred, zero_division=0)) if len(y_true) else None,
        "log_loss": None,
        "roc_auc": None,
        "confusion_matrix": confusion_matrix(y_true, y_pred, labels=[0, 1]).tolist() if len(y_true) else [[0, 0], [0, 0]],
    }
    if len(np.unique(y_true)) > 1:
        metrics["roc_auc"] = float(roc_auc_score(y_true, y_prob))
        try:
            metrics["log_loss"] = float(log_loss(y_true, np.clip(y_prob, 1e-6, 1 - 1e-6)))
        except ValueError:
            metrics["log_loss"] = None
    return json_safe(metrics)


def strategy_metrics(returns: list[float], bars_per_year: int) -> dict:
    values = np.asarray(returns, dtype=float)
    empty = {
        "total_trades": 0,
        "win_rate": None,
        "average_return": None,
        "total_return": None,
        "max_drawdown": None,
        "profit_factor": None,
        "sharpe_ratio": None,
    }
    if values.size == 0:
        return empty
    # Drop non-finite returns so cumprod / mean stay JSON-safe for Postgres.
    values = values[np.isfinite(values)]
    if values.size == 0:
        return empty
    wins = values[values > 0]
    losses = values[values < 0]
    equity = np.cumprod(1 + values)
    peak = np.maximum.accumulate(equity)
    drawdown = (equity - peak) / np.where(peak == 0, 1, peak)
    gross_profit = float(wins.sum()) if wins.size else 0.0
    gross_loss = float(abs(losses.sum())) if losses.size else 0.0
    std = float(values.std(ddof=1)) if values.size > 1 else 0.0
    sharpe = None
    if std > 0:
        sharpe = float((values.mean() / std) * math.sqrt(bars_per_year))
    return json_safe(
        {
            "total_trades": int(values.size),
            "win_rate": float((values > 0).mean()),
            "average_return": float(values.mean()),
            "total_return": float(equity[-1] - 1),
            "max_drawdown": float(drawdown.min()) if drawdown.size else 0.0,
            "profit_factor": float(gross_profit / gross_loss) if gross_loss > 0 else None,
            "sharpe_ratio": sharpe,
        }
    )
