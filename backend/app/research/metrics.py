from __future__ import annotations

import numpy as np

from app.ml.metrics import json_safe


def _longest_losing_streak(values: np.ndarray) -> int:
    longest = current = 0
    for value in values:
        if value < 0:
            current += 1
            longest = max(longest, current)
        else:
            current = 0
    return longest


def _bootstrap_expectancy(
    values: np.ndarray,
    samples: int,
    seed: int,
) -> tuple[float | None, float | None]:
    if values.size < 2 or samples < 1:
        return None, None
    rng = np.random.default_rng(seed)
    means = np.empty(samples, dtype=float)
    for index in range(samples):
        means[index] = rng.choice(values, size=values.size, replace=True).mean()
    return float(np.percentile(means, 2.5)), float(np.percentile(means, 97.5))


def research_metrics(
    net_pips: list[float],
    gross_pips: list[float],
    costs: list[float],
    *,
    candidates: int,
    bootstrap_samples: int,
    random_seed: int,
) -> dict:
    net = np.asarray(net_pips, dtype=float)
    gross = np.asarray(gross_pips, dtype=float)
    cost = np.asarray(costs, dtype=float)
    finite = np.isfinite(net)
    net = net[finite]
    gross = gross[finite] if gross.size == finite.size else gross
    cost = cost[finite] if cost.size == finite.size else cost

    if net.size == 0:
        return {
            "signals": 0,
            "candidates": int(candidates),
            "abstain_rate": 1.0 if candidates else None,
            "status": "INSUFFICIENT_SAMPLE",
            "net_expectancy_pips": None,
            "expectancy_ci_95": [None, None],
        }

    wins = net[net > 0]
    losses = net[net < 0]
    cumulative = np.cumsum(net)
    peak = np.maximum.accumulate(np.concatenate(([0.0], cumulative)))
    equity = np.concatenate(([0.0], cumulative))
    drawdown = equity - peak
    gross_profit = float(wins.sum()) if wins.size else 0.0
    gross_loss = float(abs(losses.sum())) if losses.size else 0.0
    ci_low, ci_high = _bootstrap_expectancy(net, bootstrap_samples, random_seed)

    if net.size < 50:
        status = "INSUFFICIENT_SAMPLE"
    elif ci_low is not None and ci_low > 0:
        status = "PROMISING_VALIDATION"
    else:
        status = "NO_CONVINCING_EDGE"

    return json_safe(
        {
            "signals": int(net.size),
            "candidates": int(candidates),
            "abstain_rate": float(1 - (net.size / candidates)) if candidates else None,
            "wins": int(wins.size),
            "losses": int(losses.size),
            "win_rate": float((net > 0).mean()),
            "gross_pips": float(gross.sum()) if gross.size else 0.0,
            "spread_and_transaction_cost_pips": float(cost.sum()) if cost.size else 0.0,
            "net_pips": float(net.sum()),
            "net_expectancy_pips": float(net.mean()),
            "expectancy_ci_95": [ci_low, ci_high],
            "average_win_pips": float(wins.mean()) if wins.size else None,
            "average_loss_pips": float(losses.mean()) if losses.size else None,
            "median_win_pips": float(np.median(wins)) if wins.size else None,
            "median_loss_pips": float(np.median(losses)) if losses.size else None,
            "p95_loss_pips": float(np.percentile(losses, 5)) if losses.size else None,
            "profit_factor": gross_profit / gross_loss if gross_loss else None,
            "max_drawdown_pips": float(drawdown.min()) if drawdown.size else 0.0,
            "longest_losing_streak": _longest_losing_streak(net),
            "status": status,
        }
    )
