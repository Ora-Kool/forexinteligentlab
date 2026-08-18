from app.core.config import get_settings
from app.mt5.base import MT5Connector
from app.mt5.mock import MockMT5Connector

_connector: MT5Connector | None = None


def get_connector(force_new: bool = False) -> MT5Connector:
    global _connector
    if _connector is not None and not force_new:
        return _connector
    settings = get_settings()
    mode = settings.mt5_mode.lower()
    if mode == "official":
        # Unchanged Windows path: native MetaTrader5 package next to the terminal.
        from app.mt5.official import OfficialMT5Connector

        _connector = OfficialMT5Connector()
    elif mode == "bridge":
        # macOS MetaTrader 5.app (Wine) via mt5-mac-bridge. Does not alter official.py.
        from app.mt5.bridge import BridgeMT5Connector

        _connector = BridgeMT5Connector()
    elif mode == "agent":
        # Agent mode still uses a mock-like disconnected local connector.
        # Live data arrives through the ingest API from mt5-agent.
        _connector = MockMT5Connector(available=False)
        _connector.fail_connect = True
    else:
        _connector = MockMT5Connector()
    return _connector


def reset_connector() -> None:
    global _connector
    if _connector is not None:
        try:
            _connector.disconnect()
        except Exception:
            pass
    _connector = None
