"""Bootstrap the macOS Wine → rpyc → MetaTrader5 bridge.

This module never changes the Windows OfficialMT5Connector. It only installs a
compatible ``MetaTrader5`` shim into ``sys.modules`` so the existing official
adapter can talk to MetaTrader 5.app under Wine.

Requires:
  1. MetaTrader 5.app running and logged into FBS
  2. ``scripts/mt5_native_bridge.sh serve`` listening on MT5_BRIDGE_PORT
  3. ``pip install -r backend/requirements-bridge.txt``
"""

from __future__ import annotations

import os
import sys
from typing import Any

from app.core.config import get_settings

# Standard install path inside MetaTrader 5.app's Wine prefix. OfficialMT5Connector
# only forwards path when MT5_TERMINAL_PATH is set; without it Wine returns -10003.
DEFAULT_WINE_TERMINAL_PATH = "C:/Program Files/MetaTrader 5/terminal64.exe"

_handle: Any | None = None


def _wine_terminal_path(settings: Any) -> str:
    return (settings.mt5_terminal_path or "").strip() or DEFAULT_WINE_TERMINAL_PATH


def ensure_mac_bridge() -> Any:
    """Start (or reuse) the mt5-mac-bridge client and register MetaTrader5."""
    global _handle
    if _handle is not None:
        return _handle

    settings = get_settings()
    terminal_path = _wine_terminal_path(settings)

    # Make OfficialMT5Connector.initialize() pass the Wine path on its second init
    # without editing official.py. Refresh settings cache so it sees the value.
    if not (settings.mt5_terminal_path or "").strip():
        os.environ["MT5_TERMINAL_PATH"] = terminal_path
        get_settings.cache_clear()
        settings = get_settings()

    os.environ.setdefault("MT5_BACKEND", "bridge")
    os.environ.setdefault("MT5_BRIDGE_HOST", settings.mt5_bridge_host)
    os.environ.setdefault("MT5_BRIDGE_PORT", str(settings.mt5_bridge_port))
    os.environ.setdefault("MT5_PATH", terminal_path)
    if settings.mt5_login is not None:
        os.environ.setdefault("MT5_LOGIN", str(settings.mt5_login))
    if settings.mt5_password:
        os.environ.setdefault("MT5_PASSWORD", settings.mt5_password)
    if settings.mt5_server:
        os.environ.setdefault("MT5_SERVER", settings.mt5_server)

    try:
        import mt5_mac_bridge as mt5b
    except ImportError as exc:
        raise RuntimeError(
            "mt5-mac-bridge is not installed. On macOS run:\n"
            "  pip install -r backend/requirements-bridge.txt\n"
            "and keep scripts/mt5_native_bridge.sh serve running."
        ) from exc

    init_kwargs: dict[str, Any] = {
        "backend": "bridge",
        "host": settings.mt5_bridge_host,
        "port": settings.mt5_bridge_port,
        "path": terminal_path,
        "login": str(settings.mt5_login) if settings.mt5_login is not None else None,
        "password": settings.mt5_password or None,
        "server": settings.mt5_server or None,
    }
    try:
        _handle = mt5b.init(**init_kwargs)
    except TypeError:
        # Older/newer signatures may only accept a subset of kwargs.
        try:
            _handle = mt5b.init(
                backend="bridge",
                host=settings.mt5_bridge_host,
                port=settings.mt5_bridge_port,
            )
        except TypeError:
            _handle = mt5b.init(backend="bridge", port=settings.mt5_bridge_port)
    except Exception as exc:
        raise RuntimeError(
            f"Could not reach the Wine MT5 rpyc bridge on "
            f"{settings.mt5_bridge_host}:{settings.mt5_bridge_port}. "
            f"Start MetaTrader 5.app, log into FBS, then run "
            f"`./scripts/mt5_native_bridge.sh serve`. Underlying error: {exc}"
        ) from exc

    if "MetaTrader5" not in sys.modules:
        # init() normally registers the shim; force a clear failure if it did not.
        raise RuntimeError(
            "mt5-mac-bridge initialized but did not register sys.modules['MetaTrader5']. "
            "Check the package version / API."
        )
    return _handle


def shutdown_mac_bridge() -> None:
    global _handle
    if _handle is None:
        return
    try:
        import mt5_mac_bridge as mt5b

        mt5b.shutdown(_handle)
    except Exception:
        pass
    _handle = None
    sys.modules.pop("MetaTrader5", None)
