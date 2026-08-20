from datetime import UTC, datetime, timedelta

import pytest

from app.ml.predict import predict_from_candles
from app.ml.targets import chronological_split, build_training_table
from app.ml.train import train_logistic_regression


def _trend(n: int = 200) -> list[dict]:
    origin = datetime(2024, 1, 8, 0, 0, tzinfo=UTC)
    rows = []
    price = 1.08
    for i in range(n):
        # Mild upward drift so the classifier has something to fit.
        price += 0.00008 if i % 3 else -0.00003
        rows.append(
            {
                "symbol": "EURUSD",
                "timeframe": "M5",
                "timestamp": origin + timedelta(minutes=5 * i),
                "open": price - 0.00005,
                "high": price + 0.0002,
                "low": price - 0.0002,
                "close": price,
                "spread": 0.00008,
            }
        )
    return rows


def test_chronological_split_does_not_shuffle():
    table = build_training_table(_trend(120))
    train, test = chronological_split(table, 0.2)
    assert train["timestamp"].iloc[-1] <= test["timestamp"].iloc[0]


def test_build_training_table_handles_no_candles():
    # A timeframe with no imported history used to raise KeyError('timestamp').
    assert build_training_table([]).empty


def test_training_table_does_not_label_the_unresolved_final_candle():
    candles = _trend(120)
    table = build_training_table(candles)
    assert table["timestamp"].max().to_pydatetime() < candles[-1]["timestamp"]


def test_training_untouched_timeframe_reports_missing_history():
    with pytest.raises(ValueError, match="Not enough H4 history for EURUSD"):
        train_logistic_regression(
            [],
            symbol="EURUSD",
            timeframe="H4",
            spread_cost_pips=0.8,
            transaction_cost_pips=0.2,
            pip_size=0.0001,
        )


def test_model_training_and_prediction(tmp_path, monkeypatch):
    from app.ml import train as train_mod

    monkeypatch.setattr(train_mod, "ARTIFACT_DIR", tmp_path)
    candles = _trend(180)
    result = train_logistic_regression(
        candles,
        symbol="EURUSD",
        timeframe="M5",
        spread_cost_pips=0.8,
        transaction_cost_pips=0.2,
        pip_size=0.0001,
    )
    assert result["train_samples"] > 0
    assert result["validation_samples"] > 0
    assert "accuracy" in result["classification"]
    assert "win_rate" in result["strategy"]
    prediction = predict_from_candles(result["artifact_path"], candles)
    assert prediction is not None
    assert prediction["prediction"] in {"UP", "DOWN"}
    assert 0 <= prediction["probability_up"] <= 1
    assert abs(prediction["probability_up"] + prediction["probability_down"] - 1) < 1e-6
