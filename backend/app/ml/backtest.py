from __future__ import annotations

import numpy as np

from app.core.constants import BARS_PER_YEAR, FEATURE_COLUMNS, RESEARCH_DISCLAIMER, pip_size_for
from app.ml.metrics import classification_metrics, strategy_metrics
from app.ml.targets import build_training_table
from app.ml.train import load_artifact


def run_backtest(
    candles: list[dict],
    artifact_path: str,
    min_probability: float,
    spread_cost_pips: float,
    transaction_cost_pips: float,
    symbol: str,
    timeframe: str,
) -> dict:
    artifact = load_artifact(artifact_path)
    table = build_training_table(candles)
    if table.empty:
        raise ValueError("No labeled samples available in the selected range.")

    columns = artifact["feature_columns"]
    missing = [col for col in columns if col not in table.columns]
    if missing:
        raise ValueError(f"Model features missing from dataset: {missing}")

    matrix = artifact["scaler"].transform(table[columns].to_numpy(dtype=float))
    proba = artifact["model"].predict_proba(matrix)
    classes = list(artifact["model"].classes_)
    prob_up = proba[:, classes.index(1)] if 1 in classes else np.zeros(len(table))

    pip = pip_size_for(symbol)
    cost = (spread_cost_pips + transaction_cost_pips) * pip
    trades = []
    returns = []
    y_true = []
    y_prob = []

    for idx, row in table.iterrows():
        p_up = float(prob_up[table.index.get_loc(idx)])
        y_true.append(int(row["target"]))
        y_prob.append(p_up)
        if p_up < min_probability:
            continue
        raw = (row["next_close"] - row["close"]) / row["close"]
        net = float(raw - (cost / row["close"]))
        returns.append(net)
        trades.append(
            {
                "timestamp": row["timestamp"].isoformat(),
                "price": float(row["close"]),
                "probability_up": p_up,
                "next_close": float(row["next_close"]),
                "net_return": net,
            }
        )

    return {
        "symbol": symbol,
        "timeframe": timeframe,
        "model_version": artifact["version"],
        "min_probability": min_probability,
        "spread_cost_pips": spread_cost_pips,
        "transaction_cost_pips": transaction_cost_pips,
        "classification": classification_metrics(y_true, y_prob),
        "strategy": strategy_metrics(returns, BARS_PER_YEAR.get(timeframe, 252 * 24)),
        "trades": trades[-200:],
        "trade_count": len(trades),
        "label": "Historical simulation only. Not a live trading result.",
        "disclaimer": RESEARCH_DISCLAIMER,
    }
