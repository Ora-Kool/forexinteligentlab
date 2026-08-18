from __future__ import annotations

from datetime import UTC, datetime

import numpy as np

from app.core.constants import FEATURE_COLUMNS, RESEARCH_DISCLAIMER
from app.ml.features import compute_feature_frame
from app.ml.train import load_artifact


def predict_from_candles(artifact_path: str, candles: list[dict]) -> dict | None:
    artifact = load_artifact(artifact_path)
    frame = compute_feature_frame(candles)
    if frame.empty:
        return None
    row = frame.iloc[-1]
    columns = artifact["feature_columns"]
    if row[columns].isna().any():
        return None
    vector = row[columns].to_numpy(dtype=float).reshape(1, -1)
    scaled = artifact["scaler"].transform(vector)
    proba = artifact["model"].predict_proba(scaled)[0]
    classes = list(artifact["model"].classes_)
    prob_up = float(proba[classes.index(1)]) if 1 in classes else 0.0
    prob_down = 1.0 - prob_up
    prediction = "UP" if prob_up >= 0.5 else "DOWN"
    last = candles[-1]
    return {
        "symbol": last["symbol"],
        "timeframe": last["timeframe"],
        "timestamp": datetime.now(UTC),
        "candle_timestamp": last["timestamp"],
        "price": float(last["close"]),
        "probability_up": prob_up,
        "probability_down": prob_down,
        "prediction": prediction,
        "model_version": artifact["version"],
        "disclaimer": RESEARCH_DISCLAIMER,
    }


def apply_actuals(predictions: list[dict], future_close: float, current_close: float) -> None:
    actual = 1 if future_close > current_close else 0
    for item in predictions:
        item["actual_outcome"] = actual
        item["correct"] = (item["prediction"] == "UP" and actual == 1) or (
            item["prediction"] == "DOWN" and actual == 0
        )
