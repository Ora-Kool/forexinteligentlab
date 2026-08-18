"""Feature engineering with a hard no-look-ahead contract.

Every feature at timestamp T is computed exclusively from candles whose
timestamp is <= T. Future OHLC is never referenced.
"""

from __future__ import annotations

from datetime import UTC, datetime

import numpy as np
import pandas as pd

from app.core.constants import FEATURE_COLUMNS, SESSION_ASIAN, SESSION_LONDON, SESSION_NEW_YORK, SESSION_OVERLAP


def _session_flags(ts: datetime) -> dict[str, int]:
    if ts.tzinfo is None:
        ts = ts.replace(tzinfo=UTC)
    hour = ts.astimezone(UTC).hour
    overlap = SESSION_OVERLAP[0] <= hour < SESSION_OVERLAP[1]
    london = SESSION_LONDON[0] <= hour < SESSION_LONDON[1]
    new_york = SESSION_NEW_YORK[0] <= hour < SESSION_NEW_YORK[1]
    asian = SESSION_ASIAN[0] <= hour < SESSION_ASIAN[1]
    return {
        "session_overlap": int(overlap),
        "session_london": int(london and not overlap),
        "session_new_york": int(new_york and not overlap),
        "session_asian": int(asian and not london and not new_york),
    }


def session_name(ts: datetime) -> str:
    flags = _session_flags(ts)
    if flags["session_overlap"]:
        return "London/New York overlap"
    if flags["session_london"]:
        return "London"
    if flags["session_new_york"]:
        return "New York"
    if flags["session_asian"]:
        return "Asian"
    return "Off-session"


def candles_to_frame(candles: list[dict]) -> pd.DataFrame:
    frame = pd.DataFrame(candles)
    if frame.empty:
        return frame
    frame = frame.sort_values("timestamp").drop_duplicates(subset=["timestamp"], keep="last")
    frame["timestamp"] = pd.to_datetime(frame["timestamp"], utc=True)
    return frame.reset_index(drop=True)


def compute_feature_frame(candles: list[dict] | pd.DataFrame) -> pd.DataFrame:
    """Return a frame aligned to candle timestamps with causal features only."""
    frame = candles if isinstance(candles, pd.DataFrame) else candles_to_frame(candles)
    if frame.empty:
        return frame

    close = frame["close"].astype(float)
    high = frame["high"].astype(float)
    low = frame["low"].astype(float)
    open_ = frame["open"].astype(float)
    spread = frame["spread"].astype(float) if "spread" in frame.columns else pd.Series(0.0, index=frame.index)

    out = pd.DataFrame({"timestamp": frame["timestamp"]})
    if "symbol" in frame.columns:
        out["symbol"] = frame["symbol"]
    if "timeframe" in frame.columns:
        out["timeframe"] = frame["timeframe"]

    out["sma_10"] = close.rolling(10, min_periods=10).mean()
    out["sma_20"] = close.rolling(20, min_periods=20).mean()
    out["sma_50"] = close.rolling(50, min_periods=50).mean()
    out["ema_10"] = close.ewm(span=10, adjust=False, min_periods=10).mean()
    out["ema_20"] = close.ewm(span=20, adjust=False, min_periods=20).mean()
    out["ema_50"] = close.ewm(span=50, adjust=False, min_periods=50).mean()

    delta = close.diff()
    gain = delta.clip(lower=0).rolling(14, min_periods=14).mean()
    loss = (-delta.clip(upper=0)).rolling(14, min_periods=14).mean()
    rs = gain / loss.replace(0, np.nan)
    out["rsi_14"] = 100 - (100 / (1 + rs))

    ema12 = close.ewm(span=12, adjust=False, min_periods=12).mean()
    ema26 = close.ewm(span=26, adjust=False, min_periods=26).mean()
    macd = ema12 - ema26
    signal = macd.ewm(span=9, adjust=False, min_periods=9).mean()
    out["macd"] = macd
    out["macd_signal"] = signal
    out["macd_hist"] = macd - signal

    prev_close = close.shift(1)
    tr = pd.concat(
        [(high - low).abs(), (high - prev_close).abs(), (low - prev_close).abs()],
        axis=1,
    ).max(axis=1)
    out["atr_14"] = tr.rolling(14, min_periods=14).mean()

    bb_mid = close.rolling(20, min_periods=20).mean()
    bb_std = close.rolling(20, min_periods=20).std()
    out["bb_middle"] = bb_mid
    out["bb_upper"] = bb_mid + 2 * bb_std
    out["bb_lower"] = bb_mid - 2 * bb_std
    out["bb_width"] = (out["bb_upper"] - out["bb_lower"]) / bb_mid.replace(0, np.nan)
    out["bb_pct"] = (close - out["bb_lower"]) / (out["bb_upper"] - out["bb_lower"]).replace(0, np.nan)

    returns = close.pct_change()
    out["volatility_20"] = returns.rolling(20, min_periods=20).std()
    out["return_1"] = close.pct_change(1)
    out["return_3"] = close.pct_change(3)
    out["return_5"] = close.pct_change(5)

    out["dist_sma_10"] = (close - out["sma_10"]) / close.replace(0, np.nan)
    out["dist_sma_20"] = (close - out["sma_20"]) / close.replace(0, np.nan)
    out["dist_sma_50"] = (close - out["sma_50"]) / close.replace(0, np.nan)
    out["dist_ema_10"] = (close - out["ema_10"]) / close.replace(0, np.nan)
    out["dist_ema_20"] = (close - out["ema_20"]) / close.replace(0, np.nan)
    out["dist_ema_50"] = (close - out["ema_50"]) / close.replace(0, np.nan)

    body = close - open_
    out["candle_body"] = body / close.replace(0, np.nan)
    out["upper_wick"] = (high - pd.concat([open_, close], axis=1).max(axis=1)) / close.replace(0, np.nan)
    out["lower_wick"] = (pd.concat([open_, close], axis=1).min(axis=1) - low) / close.replace(0, np.nan)
    out["hl_range"] = (high - low) / close.replace(0, np.nan)
    out["spread"] = spread.fillna(0.0)

    ts = pd.to_datetime(frame["timestamp"], utc=True)
    out["hour_of_day"] = ts.dt.hour
    out["day_of_week"] = ts.dt.dayofweek
    flags = [_session_flags(value.to_pydatetime()) for value in ts]
    flag_frame = pd.DataFrame(flags)
    for column in ("session_asian", "session_london", "session_new_york", "session_overlap"):
        out[column] = flag_frame[column].to_numpy()

    return out


def latest_feature_dict(candles: list[dict]) -> dict | None:
    frame = compute_feature_frame(candles)
    if frame.empty:
        return None
    row = frame.iloc[-1]
    if row[FEATURE_COLUMNS].isna().any():
        return None
    ts = row["timestamp"].to_pydatetime()
    payload = {column: _to_python(row[column]) for column in FEATURE_COLUMNS}
    payload["timestamp"] = ts.isoformat()
    payload["candle_timestamp"] = ts
    payload["trading_session"] = session_name(ts)
    return payload


def _to_python(value):
    if pd.isna(value):
        return None
    if hasattr(value, "item"):
        return value.item()
    return value
