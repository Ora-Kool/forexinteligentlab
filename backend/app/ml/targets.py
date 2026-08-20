"""Prediction target construction.

Default research target:
    target = 1 if next_close > current_close else 0

The target uses the NEXT candle close. Features must never include that
future close. The last row has no target and is dropped for training.
"""

from __future__ import annotations

import pandas as pd
import numpy as np

from app.core.constants import FEATURE_COLUMNS
from app.ml.features import compute_feature_frame


def add_next_close_target(candle_frame: pd.DataFrame) -> pd.DataFrame:
    frame = candle_frame.sort_values("timestamp").copy()
    frame["next_close"] = frame["close"].shift(-1)
    # The final candle is not DOWN; it is unknown until a future close exists.
    frame["target"] = np.where(
        frame["next_close"].notna(),
        (frame["next_close"] > frame["close"]).astype(float),
        np.nan,
    )
    return frame


def build_training_table(candles: list[dict] | pd.DataFrame) -> pd.DataFrame:
    """Join causal features with the next-close target.

    Rows that would require future information in features are impossible
    by construction: features are rolling/causal, target is a forward shift
    that is excluded from the feature matrix.
    """
    raw = candles if isinstance(candles, pd.DataFrame) else pd.DataFrame(candles)
    if raw.empty or "timestamp" not in raw.columns:
        return pd.DataFrame(columns=[*FEATURE_COLUMNS, "timestamp", "close", "target", "next_close"])

    raw = raw.copy()
    raw["timestamp"] = pd.to_datetime(raw["timestamp"], utc=True)
    raw = raw.sort_values("timestamp").reset_index(drop=True)

    features = compute_feature_frame(raw)
    labeled = add_next_close_target(raw[["timestamp", "close"]].copy())
    features["timestamp"] = pd.to_datetime(features["timestamp"], utc=True)
    labeled["timestamp"] = pd.to_datetime(labeled["timestamp"], utc=True)
    merged = features.merge(labeled[["timestamp", "close", "target", "next_close"]], on="timestamp", how="left")
    if "timestamp" not in merged.columns:
        merged = merged.reset_index()
    merged = merged.dropna(subset=FEATURE_COLUMNS + ["target"])
    return merged.reset_index(drop=True)


def chronological_split(frame: pd.DataFrame, test_ratio: float = 0.2) -> tuple[pd.DataFrame, pd.DataFrame]:
    if frame.empty:
        return frame, frame
    ordered = frame.sort_values("timestamp")
    split = max(1, int(len(ordered) * (1 - test_ratio)))
    # Never shuffle financial time series.
    train = ordered.iloc[:split].copy()
    test = ordered.iloc[split:].copy()
    return train, test
