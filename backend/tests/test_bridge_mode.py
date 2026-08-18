"""Bridge mode wires a wrapper; official/mock/agent adapters stay untouched."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from app.mt5.base import MT5Status
from app.mt5.factory import get_connector, reset_connector


def test_bridge_mode_uses_wrapper_not_raw_official(monkeypatch):
    monkeypatch.setenv("MT5_MODE", "bridge")
    monkeypatch.setenv("MT5_BRIDGE_HOST", "127.0.0.1")
    monkeypatch.setenv("MT5_BRIDGE_PORT", "18813")

    from app.core.config import get_settings

    get_settings.cache_clear()
    reset_connector()

    fake_status = MT5Status(connected=True, mode="official", trade_allowed=False)
    inner = MagicMock()
    inner.connect.return_value = fake_status
    inner.status.return_value = fake_status
    inner.discover_symbols.return_value = []
    inner.resolve_symbol.return_value = None
    inner.copy_rates_from_pos.return_value = []
    inner.symbol_tick.return_value = None

    with (
        patch("app.mt5.bridge.ensure_mac_bridge", return_value=SimpleNamespace()),
        patch("app.mt5.bridge.OfficialMT5Connector", return_value=inner),
    ):
        connector = get_connector(force_new=True)
        status = connector.connect()

    assert type(connector).__name__ == "BridgeMT5Connector"
    assert status.mode == "bridge"
    assert status.trade_allowed is False
    assert status.details.get("bridge") is True
    inner.connect.assert_called_once()

    reset_connector()
    get_settings.cache_clear()
