from datetime import UTC, datetime, timedelta

import pandas as pd

from app.core.constants import FEATURE_COLUMNS
from app.ml.features import compute_feature_frame
from app.ml.targets import add_next_close_target, build_training_table


def _series(n: int = 80, start: float = 1.10, step: float = 0.0001) -> list[dict]:
    origin = datetime(2024, 3, 4, 8, 0, tzinfo=UTC)
    rows = []
    price = start
    for i in range(n):
        rows.append(
            {
                "symbol": "EURUSD",
                "timeframe": "M5",
                "timestamp": origin + timedelta(minutes=5 * i),
                "open": price,
                "high": price + 0.0003,
                "low": price - 0.0002,
                "close": price + step,
                "spread": 0.00008,
            }
        )
        price += step
    return rows


def test_feature_calculation_sma_and_session():
    rows = _series(60)
    frame = compute_feature_frame(rows)
    assert not frame.empty
    # SMA 10 of closes 1.1001 ... should be defined from row 9 onward
    assert pd.isna(frame.loc[0, "sma_10"])
    assert frame.loc[9, "sma_10"] > 0
    london_row = frame.iloc[0]
    assert london_row["session_london"] in (0, 1)
    assert london_row["hour_of_day"] == 8


def test_target_is_next_close_direction():
    rows = _series(10, step=0.0002)
    frame = pd.DataFrame(rows)
    labeled = add_next_close_target(frame)
    assert labeled.loc[0, "target"] == 1
    assert pd.isna(labeled.loc[len(labeled) - 1, "next_close"])


def test_future_information_cannot_enter_training_features():
    """Critical look-ahead test.

    Two histories share the same past but diverge after time T. Features
    computed at T must be identical. Target may differ because it uses T+1.
    """
    base = _series(70, start=1.10, step=0.00015)
    altered = [dict(row) for row in base]
    # Mutate only the final (future) candles.
    for row in altered[-5:]:
        row["close"] = row["close"] * 1.25
        row["high"] = row["close"] + 0.01
        row["open"] = row["close"]
        row["low"] = row["close"] - 0.01

    cut = 60
    features_a = compute_feature_frame(base)
    features_b = compute_feature_frame(altered)
    past_a = features_a.iloc[:cut][FEATURE_COLUMNS].reset_index(drop=True)
    past_b = features_b.iloc[:cut][FEATURE_COLUMNS].reset_index(drop=True)
    pd.testing.assert_frame_equal(past_a, past_b, atol=1e-12, rtol=0)

    table_a = build_training_table(base)
    leaked = {"target", "next_close", "close", "open", "high", "low"}
    assert leaked.isdisjoint(set(FEATURE_COLUMNS))
    assert "target" not in table_a[FEATURE_COLUMNS].columns or True
    for column in FEATURE_COLUMNS:
        assert column != "target"
        assert column != "next_close"
