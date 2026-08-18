"""Shared constants. Research platform — no live order execution."""

from datetime import timedelta

TIMEFRAMES = ("M1", "M5", "M15", "M30", "H1", "H4", "D1")

TIMEFRAME_MINUTES = {
    "M1": 1,
    "M5": 5,
    "M15": 15,
    "M30": 30,
    "H1": 60,
    "H4": 240,
    "D1": 1440,
}

TIMEFRAME_MT5 = {
    "M1": 1,
    "M5": 5,
    "M15": 15,
    "M30": 30,
    "H1": 16385,
    "H4": 16388,
    "D1": 16408,
}

PREFERRED_BASES = (
    "EURUSD",
    "GBPUSD",
    "USDJPY",
    "USDCHF",
    "AUDUSD",
    "USDCAD",
    "NZDUSD",
    "EURGBP",
    "GBPJPY",
    "EURJPY",
    "XAUUSD",
)

DEFAULT_MONITOR = (
    ("EURUSD", "M5"),
    ("GBPUSD", "M5"),
    ("USDJPY", "M5"),
    ("XAUUSD", "M5"),
    ("AUDUSD", "M5"),
    ("USDCAD", "M5"),
)

SYMBOL_SUFFIXES = ("", ".a", "m", ".pro", ".r", ".i", "#")

# Typical pip size for display. Gold uses 0.1 as 1 pip convention here.
PIP_SIZE = {
    "XAUUSD": 0.1,
    "USDJPY": 0.01,
    "EURJPY": 0.01,
    "GBPJPY": 0.01,
}

DEFAULT_PIP_SIZE = 0.0001

# Trading sessions in UTC.
# Asian 00:00–09:00, London 08:00–17:00, New York 13:00–22:00
# Overlap London/New York 13:00–17:00
SESSION_ASIAN = (0, 9)
SESSION_LONDON = (8, 17)
SESSION_NEW_YORK = (13, 22)
SESSION_OVERLAP = (13, 17)

FEATURE_COLUMNS = [
    "sma_10",
    "sma_20",
    "sma_50",
    "ema_10",
    "ema_20",
    "ema_50",
    "rsi_14",
    "macd",
    "macd_signal",
    "macd_hist",
    "atr_14",
    "bb_upper",
    "bb_middle",
    "bb_lower",
    "bb_width",
    "bb_pct",
    "volatility_20",
    "return_1",
    "return_3",
    "return_5",
    "dist_sma_10",
    "dist_sma_20",
    "dist_sma_50",
    "dist_ema_10",
    "dist_ema_20",
    "dist_ema_50",
    "candle_body",
    "upper_wick",
    "lower_wick",
    "hl_range",
    "spread",
    "hour_of_day",
    "day_of_week",
    "session_asian",
    "session_london",
    "session_new_york",
    "session_overlap",
]

RESEARCH_DISCLAIMER = (
    "Research prediction only. Not a trading recommendation. "
    "Historical results do not guarantee future performance. "
    "This platform does not place orders."
)

BARS_PER_YEAR = {
    "M1": 252 * 24 * 60,
    "M5": 252 * 24 * 12,
    "M15": 252 * 24 * 4,
    "M30": 252 * 24 * 2,
    "H1": 252 * 24,
    "H4": 252 * 6,
    "D1": 252,
}


def pip_size_for(symbol: str) -> float:
    base = "".join(ch for ch in symbol.upper() if ch.isalpha())
    for key, value in PIP_SIZE.items():
        if key in base:
            return value
    if base.endswith("JPY"):
        return 0.01
    return DEFAULT_PIP_SIZE


def timeframe_delta(timeframe: str) -> timedelta:
    return timedelta(minutes=TIMEFRAME_MINUTES[timeframe])
