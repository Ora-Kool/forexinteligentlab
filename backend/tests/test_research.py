from __future__ import annotations

from datetime import UTC, datetime, timedelta

import numpy as np

from app.mt5.base import CandleRecord
from app.research.config import ResearchConfig
from app.research.evaluator import run_walk_forward_experiment
from app.research.targets import build_triple_barrier_table
from app.services.candles import upsert_candles


def _market(n: int = 2200, symbol: str = "RSRCH") -> list[dict]:
    rng = np.random.default_rng(17)
    origin = datetime(2025, 1, 6, tzinfo=UTC)
    price = 1.1000
    rows = []
    for index in range(n):
        regime = 0.00005 if (index // 180) % 2 == 0 else -0.00004
        change = regime + float(rng.normal(0, 0.00025))
        open_price = price
        price = max(0.5, price + change)
        wick = float(rng.uniform(0.00008, 0.00035))
        rows.append(
            {
                "symbol": symbol,
                "timeframe": "M5",
                "timestamp": origin + timedelta(minutes=5 * index),
                "open": open_price,
                "high": max(open_price, price) + wick,
                "low": min(open_price, price) - wick,
                "close": price,
                "spread": 0.00008,
                "tick_volume": 100 + index % 30,
            }
        )
    return rows


def _config() -> ResearchConfig:
    return ResearchConfig(
        tp_atr=0.8,
        sl_atr=0.8,
        timeout_bars=6,
        folds=2,
        min_train_bars=600,
        validation_bars=300,
        minimum_tuning_signals=5,
        minimum_validation_signals=5,
        thresholds=(0.50, 0.55, 0.60, 0.65),
        bootstrap_samples=100,
    )


def test_triple_barrier_builds_two_sided_cost_aware_candidates():
    table = build_triple_barrier_table(_market(300), _config(), pip_size=0.0001)
    assert not table.empty
    assert set(table["side_name"]) == {"UP", "DOWN"}
    assert table["event_end_index"].gt(table["bar_index"]).all()
    assert table["cost_pips"].ge(1.0).all()
    assert np.allclose(table["net_pips"], table["gross_pips"] - table["cost_pips"])
    assert table["target"].isin([0, 1]).all()


def test_walk_forward_is_purged_and_can_abstain():
    config = _config()
    table = build_triple_barrier_table(_market(), config, pip_size=0.0001)
    result = run_walk_forward_experiment(table, config)
    assert len(result["folds"]) == 2
    assert result["metrics"]["folds"] == 2
    assert 0 <= result["metrics"]["abstain_rate"] <= 1
    for fold in result["folds"]:
        assert fold["train_end"] < fold["validation_start"]
        assert fold["threshold"] in config.thresholds
        assert "net_expectancy_pips" in fold["metrics"]


def test_research_experiment_api_persists_folds(client, auth_headers, db_session):
    rows = [
        CandleRecord(
            symbol=item["symbol"],
            timeframe=item["timeframe"],
            timestamp=item["timestamp"],
            open=item["open"],
            high=item["high"],
            low=item["low"],
            close=item["close"],
            spread=item["spread"],
            tick_volume=item["tick_volume"],
        )
        for item in _market(1800, symbol="APITEST")
    ]
    upsert_candles(db_session, rows)

    response = client.post(
        "/api/research/experiments",
        headers=auth_headers,
        json={
            "symbol": "APITEST",
            "timeframe": "M5",
            "tp_atr": 0.8,
            "sl_atr": 0.8,
            "timeout_bars": 6,
            "folds": 2,
            "min_train_bars": 500,
            "validation_bars": 250,
            "minimum_tuning_signals": 5,
            "minimum_validation_signals": 5,
            "thresholds": [0.5, 0.55, 0.6],
            "bootstrap_samples": 100,
        },
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["dataset_version"].startswith("sha256:")
    assert len(body["folds"]) == 2
    assert body["metrics"]["methodology"]["split"] == "purged expanding walk-forward"

    listing = client.get("/api/research/experiments", headers=auth_headers)
    assert listing.status_code == 200
    assert any(item["id"] == body["id"] for item in listing.json())
