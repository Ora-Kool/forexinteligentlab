from __future__ import annotations

import numpy as np
import pandas as pd

from app.core.constants import FEATURE_COLUMNS
from app.ml.features import compute_feature_frame
from app.research.config import ResearchConfig


def _barrier_outcome(
    frame: pd.DataFrame,
    index: int,
    side: int,
    entry: float,
    tp_distance: float,
    sl_distance: float,
    timeout_bars: int,
    pip_size: float,
    cost_pips: float,
    minimum_edge_pips: float,
    ambiguity_policy: str,
) -> dict | None:
    """Label one side without using information after the event end.

    ``side`` is +1 for long and -1 for short. If both barriers are touched in
    the same OHLC bar, ordering is unknowable; pessimistic means a loss.
    """

    if side == 1:
        take_price = entry + tp_distance
        stop_price = entry - sl_distance
    else:
        take_price = entry - tp_distance
        stop_price = entry + sl_distance

    final_index = min(index + timeout_bars, len(frame) - 1)
    for future_index in range(index + 1, final_index + 1):
        row = frame.iloc[future_index]
        if side == 1:
            take_hit = float(row["high"]) >= take_price
            stop_hit = float(row["low"]) <= stop_price
        else:
            take_hit = float(row["low"]) <= take_price
            stop_hit = float(row["high"]) >= stop_price

        if take_hit and stop_hit:
            if ambiguity_policy == "exclude":
                return None
            gross_pips = -(sl_distance / pip_size)
            return {
                "target": 0,
                "outcome": "AMBIGUOUS_LOSS",
                "gross_pips": gross_pips,
                "net_pips": gross_pips - cost_pips,
                "event_end_index": future_index,
                "event_end": row["timestamp"],
                "ambiguous": True,
            }
        if take_hit:
            gross_pips = tp_distance / pip_size
            net_pips = gross_pips - cost_pips
            return {
                "target": int(net_pips >= minimum_edge_pips),
                "outcome": "TAKE_PROFIT",
                "gross_pips": gross_pips,
                "net_pips": net_pips,
                "event_end_index": future_index,
                "event_end": row["timestamp"],
                "ambiguous": False,
            }
        if stop_hit:
            gross_pips = -(sl_distance / pip_size)
            return {
                "target": 0,
                "outcome": "STOP_LOSS",
                "gross_pips": gross_pips,
                "net_pips": gross_pips - cost_pips,
                "event_end_index": future_index,
                "event_end": row["timestamp"],
                "ambiguous": False,
            }

    timeout_close = float(frame.iloc[final_index]["close"])
    gross_pips = side * (timeout_close - entry) / pip_size
    net_pips = gross_pips - cost_pips
    return {
        "target": int(net_pips >= minimum_edge_pips),
        "outcome": "TIMEOUT",
        "gross_pips": gross_pips,
        "net_pips": net_pips,
        "event_end_index": final_index,
        "event_end": frame.iloc[final_index]["timestamp"],
        "ambiguous": False,
    }


def build_triple_barrier_table(
    candles: list[dict] | pd.DataFrame,
    config: ResearchConfig,
    pip_size: float,
) -> pd.DataFrame:
    """Build causal features plus side-specific triple-barrier outcomes.

    Each timestamp produces a long and short research candidate. Features are
    identical and known at entry; only labels inspect the future window.
    """

    config.validate()
    raw = candles.copy() if isinstance(candles, pd.DataFrame) else pd.DataFrame(candles)
    if raw.empty or len(raw) <= config.timeout_bars:
        return pd.DataFrame()
    raw["timestamp"] = pd.to_datetime(raw["timestamp"], utc=True)
    raw = raw.sort_values("timestamp").drop_duplicates("timestamp", keep="last").reset_index(drop=True)

    features = compute_feature_frame(raw)
    joined = raw[["timestamp", "open", "high", "low", "close"]].merge(
        features,
        on="timestamp",
        how="left",
    )
    valid_features = joined[FEATURE_COLUMNS].replace([np.inf, -np.inf], np.nan).notna().all(axis=1)

    records: list[dict] = []
    last_entry = len(joined) - config.timeout_bars
    for index in range(last_entry):
        if not bool(valid_features.iloc[index]):
            continue
        row = joined.iloc[index]
        atr = float(row["atr_14"])
        if not np.isfinite(atr) or atr <= 0:
            continue
        entry = float(row["close"])
        spread = float(row["spread"] or 0.0)
        observed_spread_pips = spread / pip_size if spread > 0 and pip_size > 0 else 0.0
        spread_cost = max(config.spread_cost_pips, observed_spread_pips)
        cost_pips = spread_cost + config.transaction_cost_pips
        tp_distance = atr * config.tp_atr
        sl_distance = atr * config.sl_atr

        base = {
            "bar_index": index,
            "timestamp": row["timestamp"],
            "entry_price": entry,
            "atr": atr,
            "spread_cost_pips": spread_cost,
            "transaction_cost_pips": config.transaction_cost_pips,
            "cost_pips": cost_pips,
            **{column: row[column] for column in FEATURE_COLUMNS},
        }
        for side, side_name in ((1, "UP"), (-1, "DOWN")):
            outcome = _barrier_outcome(
                joined,
                index,
                side,
                entry,
                tp_distance,
                sl_distance,
                config.timeout_bars,
                pip_size,
                cost_pips,
                config.minimum_edge_pips,
                config.ambiguity_policy,
            )
            if outcome is None:
                continue
            records.append({**base, "side": side, "side_name": side_name, **outcome})

    return pd.DataFrame.from_records(records)
