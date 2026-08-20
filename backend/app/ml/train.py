from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import joblib
import numpy as np
from sklearn.linear_model import LogisticRegression
from sklearn.preprocessing import StandardScaler

from app.core.constants import BARS_PER_YEAR, FEATURE_COLUMNS, RESEARCH_DISCLAIMER
from app.ml.metrics import classification_metrics, strategy_metrics
from app.ml.targets import build_training_table, chronological_split


ARTIFACT_DIR = Path(__file__).resolve().parents[2] / "data" / "models"


def train_logistic_regression(
    candles: list[dict],
    symbol: str,
    timeframe: str,
    spread_cost_pips: float,
    transaction_cost_pips: float,
    pip_size: float,
    min_probability: float = 0.5,
) -> dict:
    table = build_training_table(candles)
    if len(table) < 80:
        raise ValueError(
            f"Not enough {timeframe} history for {symbol}: {len(candles)} candles gave "
            f"{len(table)} labeled bars, need at least 80 after feature warmup. "
            f"Import more {timeframe} history from Settings, or enable {symbol} {timeframe} "
            "in the monitor so auto-backfill can fill it."
        )

    train, test = chronological_split(table, test_ratio=0.2)
    if train.empty or test.empty:
        raise ValueError("Chronological split produced an empty train or test set.")

    feature_cols = [col for col in FEATURE_COLUMNS if col in table.columns]
    # Safety: target and next_close must never be features.
    leaked = {"target", "next_close", "close", "open", "high", "low"}
    feature_cols = [col for col in feature_cols if col not in leaked]

    scaler = StandardScaler()
    x_train = scaler.fit_transform(train[feature_cols].to_numpy(dtype=float))
    x_test = scaler.transform(test[feature_cols].to_numpy(dtype=float))
    y_train = train["target"].to_numpy(dtype=int)
    y_test = test["target"].to_numpy(dtype=int)

    model = LogisticRegression(max_iter=400, class_weight="balanced")
    model.fit(x_train, y_train)
    probabilities = model.predict_proba(x_test)[:, 1]
    class_metrics = classification_metrics(y_test, probabilities)

    test = test.copy()
    test["probability_up"] = probabilities
    test["prediction"] = np.where(test["probability_up"] >= 0.5, 1, 0)
    cost = (spread_cost_pips + transaction_cost_pips) * pip_size
    returns: list[float] = []
    for _, row in test.iterrows():
        if row["probability_up"] < min_probability:
            continue
        # Long-only research simulation when the model predicts UP.
        if row["prediction"] != 1:
            continue
        raw = (row["next_close"] - row["close"]) / row["close"]
        returns.append(float(raw - (cost / row["close"])))

    strat = strategy_metrics(returns, BARS_PER_YEAR.get(timeframe, 252 * 24))
    version = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    ARTIFACT_DIR.mkdir(parents=True, exist_ok=True)
    path = ARTIFACT_DIR / f"{symbol}_{timeframe}_{version}.joblib"
    joblib.dump(
        {
            "model": model,
            "scaler": scaler,
            "feature_columns": feature_cols,
            "symbol": symbol,
            "timeframe": timeframe,
            "version": version,
            "disclaimer": RESEARCH_DISCLAIMER,
        },
        path,
    )
    return {
        "name": "logistic_next_close",
        "version": version,
        "algorithm": "LogisticRegression",
        "symbol": symbol,
        "timeframe": timeframe,
        "feature_list": feature_cols,
        "training_start": train["timestamp"].iloc[0].to_pydatetime(),
        "training_end": test["timestamp"].iloc[-1].to_pydatetime(),
        "train_samples": int(len(train)),
        "validation_samples": int(len(test)),
        "classification": class_metrics,
        "strategy": strat,
        "artifact_path": str(path),
        "disclaimer": RESEARCH_DISCLAIMER,
    }


def load_artifact(path: str) -> dict:
    return joblib.load(path)
