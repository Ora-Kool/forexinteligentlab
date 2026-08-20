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

# Typical pip size for display and paper costs.
# Gold: 0.1. JPY pairs: 0.01. Crypto CFDs: 1.0 ($1). Majors: 0.0001.
PIP_SIZE = {
    "XAUUSD": 0.1,
    "XAGUSD": 0.01,
    "USDJPY": 0.01,
    "EURJPY": 0.01,
    "GBPJPY": 0.01,
    "BTCUSD": 1.0,
    "ETHUSD": 1.0,
}

DEFAULT_PIP_SIZE = 0.0001
CRYPTO_PIP_SIZE = 1.0
_CRYPTO_MARKERS = ("BTC", "XBT", "ETH", "SOL", "XRP", "LTC", "ADA", "DOGE", "BNB")

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
    if any(marker in base for marker in _CRYPTO_MARKERS):
        return CRYPTO_PIP_SIZE
    if base.endswith("JPY"):
        return 0.01
    return DEFAULT_PIP_SIZE


def spread_pips(spread: float | None, symbol: str) -> float | None:
    if spread is None:
        return None
    size = pip_size_for(symbol)
    if not size:
        return None
    return float(spread) / size


def spread_bps(spread: float | None, price: float | None) -> float | None:
    if spread is None or price in (None, 0):
        return None
    return abs(float(spread)) / abs(float(price)) * 10_000


def spread_is_wide(
    *,
    spread: float | None,
    price: float | None,
    symbol: str,
    pip_threshold: float,
    bps_threshold: float,
) -> bool:
    """True only if the spread is wide in both pip and relative (bps) terms.

    A $20 BTC spread is ~20 crypto-pips but ~3 bps of price — normal, not an
    FX-style 5-pip blowout. Requiring both gates stops that false alarm.
    """
    pips = spread_pips(spread, symbol)
    bps = spread_bps(spread, price)
    if pips is None or bps is None:
        return False
    return pips >= pip_threshold and bps >= bps_threshold


def timeframe_delta(timeframe: str) -> timedelta:
    return timedelta(minutes=TIMEFRAME_MINUTES[timeframe])
