from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd
from sklearn.linear_model import LogisticRegression
from sklearn.preprocessing import StandardScaler

from app.core.constants import FEATURE_COLUMNS
from app.research.config import ResearchConfig
from app.research.metrics import research_metrics


@dataclass
class _SideModel:
    scaler: StandardScaler
    model: LogisticRegression

    def probabilities(self, rows: pd.DataFrame) -> np.ndarray:
        matrix = self.scaler.transform(rows[FEATURE_COLUMNS].to_numpy(dtype=float))
        classes = list(self.model.classes_)
        probabilities = self.model.predict_proba(matrix)
        return probabilities[:, classes.index(1)]


def _fit_side(rows: pd.DataFrame) -> _SideModel:
    if rows.empty or rows["target"].nunique() < 2:
        raise ValueError("A research fold needs both positive and negative barrier outcomes.")
    scaler = StandardScaler()
    matrix = scaler.fit_transform(rows[FEATURE_COLUMNS].to_numpy(dtype=float))
    model = LogisticRegression(max_iter=400, class_weight="balanced")
    model.fit(matrix, rows["target"].to_numpy(dtype=int))
    return _SideModel(scaler=scaler, model=model)


def _score_sides(
    train: pd.DataFrame,
    evaluation: pd.DataFrame,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    scored: list[pd.DataFrame] = []
    for side in (1, -1):
        side_train = train[train["side"] == side]
        side_eval = evaluation[evaluation["side"] == side].copy()
        fitted = _fit_side(side_train)
        side_eval["probability"] = fitted.probabilities(side_eval)
        scored.append(side_eval)
    return scored[0], scored[1]


def _select_signals(
    up: pd.DataFrame,
    down: pd.DataFrame,
    threshold: float,
) -> tuple[list[dict], int]:
    """Choose one direction per bar and prohibit overlapping paper positions."""

    up_by_bar = {int(row.bar_index): row for row in up.itertuples(index=False)}
    down_by_bar = {int(row.bar_index): row for row in down.itertuples(index=False)}
    bars = sorted(set(up_by_bar) & set(down_by_bar))
    selected: list[dict] = []
    blocked_until = -1
    for bar_index in bars:
        if bar_index <= blocked_until:
            continue
        up_row = up_by_bar[bar_index]
        down_row = down_by_bar[bar_index]
        candidate = up_row if up_row.probability >= down_row.probability else down_row
        if float(candidate.probability) < threshold:
            continue
        selected.append(
            {
                "bar_index": bar_index,
                "timestamp": candidate.timestamp,
                "side": candidate.side_name,
                "probability": float(candidate.probability),
                "outcome": candidate.outcome,
                "gross_pips": float(candidate.gross_pips),
                "cost_pips": float(candidate.cost_pips),
                "net_pips": float(candidate.net_pips),
                "event_end": candidate.event_end,
                "event_end_index": int(candidate.event_end_index),
            }
        )
        blocked_until = int(candidate.event_end_index)
    return selected, len(bars)


def _signal_metrics(signals: list[dict], candidates: int, config: ResearchConfig, seed: int) -> dict:
    return research_metrics(
        [item["net_pips"] for item in signals],
        [item["gross_pips"] for item in signals],
        [item["cost_pips"] for item in signals],
        candidates=candidates,
        bootstrap_samples=config.bootstrap_samples,
        random_seed=seed,
    )


def _choose_threshold(
    up: pd.DataFrame,
    down: pd.DataFrame,
    config: ResearchConfig,
) -> tuple[float, dict]:
    best_threshold = config.thresholds[-1]
    best_metrics: dict | None = None
    best_expectancy = float("-inf")
    for threshold in config.thresholds:
        signals, candidates = _select_signals(up, down, threshold)
        metrics = _signal_metrics(signals, candidates, config, config.random_seed)
        expectancy = metrics.get("net_expectancy_pips")
        if len(signals) < config.minimum_tuning_signals or expectancy is None:
            continue
        if expectancy > best_expectancy:
            best_threshold = threshold
            best_metrics = metrics
            best_expectancy = expectancy
    if best_metrics is None:
        signals, candidates = _select_signals(up, down, best_threshold)
        best_metrics = _signal_metrics(signals, candidates, config, config.random_seed)
    return float(best_threshold), best_metrics


def run_walk_forward_experiment(table: pd.DataFrame, config: ResearchConfig) -> dict:
    """Run nested, purged expanding-window evaluation.

    Thresholds are selected on an inner tuning tail. The outer validation fold
    is not used for fitting or threshold selection. Label horizons are purged
    from both boundaries so event outcomes cannot cross into the next period.
    """

    config.validate()
    if table.empty:
        raise ValueError("Triple-barrier target table is empty.")
    bars = sorted(int(value) for value in table["bar_index"].unique())
    maximum_folds = (len(bars) - config.min_train_bars) // config.validation_bars
    fold_count = min(config.folds, maximum_folds)
    if fold_count < 1:
        required = config.min_train_bars + config.validation_bars
        raise ValueError(
            f"Insufficient target bars for purged walk-forward: have {len(bars)}, need at least {required}."
        )

    first_validation_position = len(bars) - fold_count * config.validation_bars
    fold_payloads: list[dict] = []
    all_signals: list[dict] = []
    total_candidates = 0

    for fold_index in range(fold_count):
        validation_position = first_validation_position + fold_index * config.validation_bars
        validation_bars = bars[validation_position : validation_position + config.validation_bars]
        validation_start = validation_bars[0]
        validation_end = validation_bars[-1]

        pre_validation = [bar for bar in bars[:validation_position] if bar + config.timeout_bars < validation_start]
        tune_count = max(100, int(len(pre_validation) * config.tuning_ratio))
        tune_start_position = len(pre_validation) - tune_count
        if tune_start_position <= 100:
            raise ValueError("Insufficient inner-training history after purging.")
        tune_start = pre_validation[tune_start_position]
        fit_bars = [bar for bar in pre_validation[:tune_start_position] if bar + config.timeout_bars < tune_start]
        tune_bars = pre_validation[tune_start_position:]

        fit = table[table["bar_index"].isin(fit_bars)]
        tuning = table[table["bar_index"].isin(tune_bars)]
        training = table[table["bar_index"].isin(pre_validation)]
        validation = table[table["bar_index"].isin(validation_bars)]

        tune_up, tune_down = _score_sides(fit, tuning)
        threshold, tuning_metrics = _choose_threshold(tune_up, tune_down, config)

        validation_up, validation_down = _score_sides(training, validation)
        signals, candidates = _select_signals(validation_up, validation_down, threshold)
        metrics = _signal_metrics(signals, candidates, config, config.random_seed + fold_index + 1)
        if len(signals) < config.minimum_validation_signals:
            metrics["status"] = "INSUFFICIENT_SAMPLE"

        timestamps = table.drop_duplicates("bar_index").set_index("bar_index")["timestamp"]
        fold_payloads.append(
            {
                "fold_index": fold_index + 1,
                "threshold": threshold,
                "train_start": timestamps.loc[pre_validation[0]],
                "train_end": timestamps.loc[pre_validation[-1]],
                "validation_start": timestamps.loc[validation_start],
                "validation_end": timestamps.loc[validation_end],
                "train_samples": int(len(training)),
                "validation_samples": int(len(validation)),
                "signals": len(signals),
                "tuning_metrics": tuning_metrics,
                "metrics": metrics,
            }
        )
        all_signals.extend(signals)
        total_candidates += candidates

    aggregate = _signal_metrics(all_signals, total_candidates, config, config.random_seed + 1000)
    fold_expectancies = [
        fold["metrics"].get("net_expectancy_pips")
        for fold in fold_payloads
        if fold["metrics"].get("net_expectancy_pips") is not None
    ]
    aggregate["folds"] = fold_count
    aggregate["positive_folds"] = sum(value > 0 for value in fold_expectancies)
    aggregate["negative_folds"] = sum(value <= 0 for value in fold_expectancies)
    aggregate["stable_across_folds"] = bool(fold_expectancies) and all(value > 0 for value in fold_expectancies)
    if not aggregate["stable_across_folds"] and aggregate["status"] == "PROMISING_VALIDATION":
        aggregate["status"] = "REGIME_DEPENDENT"

    return {
        "metrics": aggregate,
        "folds": fold_payloads,
        "signals": all_signals[-200:],
        "methodology": {
            "split": "purged expanding walk-forward",
            "threshold_selection": "inner tuning tail, selected by after-cost expectancy",
            "concurrency": "one active paper signal per symbol",
            "ambiguity": config.ambiguity_policy,
            "holdout": "not implemented in this first milestone; results are validation-only",
        },
    }
