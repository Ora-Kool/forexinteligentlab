from app.core.constants import pip_size_for, spread_bps, spread_is_wide, spread_pips


def test_pip_size_crypto_is_one_dollar():
    assert pip_size_for("BTCUSD") == 1.0
    assert pip_size_for("ETHUSD") == 1.0
    assert pip_size_for("EURUSD") == 0.0001
    assert pip_size_for("USDJPY") == 0.01
    assert pip_size_for("XAUUSD") == 0.1


def test_btcusd_spread_is_not_a_196500_pip_fx_quote():
    # Live FBS quote: ~$19.65 on ~$71,757 — 19.65 crypto-pips, ~2.7 bps.
    spread = 19.65
    price = 71757.5
    assert round(spread_pips(spread, "BTCUSD"), 2) == 19.65
    assert spread_bps(spread, price) < 4
    assert spread_is_wide(
        spread=spread,
        price=price,
        symbol="BTCUSD",
        pip_threshold=5.0,
        bps_threshold=8.0,
    ) is False


def test_wide_fx_spread_still_alerts():
    assert spread_is_wide(
        spread=0.0010,
        price=1.1700,
        symbol="EURUSD",
        pip_threshold=5.0,
        bps_threshold=8.0,
    ) is True
