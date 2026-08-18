"""Mac Wine bridge connector.

Wraps the existing Windows OfficialMT5Connector after bootstrapping
mt5-mac-bridge. Official / mock / agent adapters are left untouched.
"""

from __future__ import annotations

from datetime import datetime

from app.core.config import get_settings
from app.core.constants import PREFERRED_BASES, SYMBOL_SUFFIXES
from app.mt5.base import CandleRecord, MT5Connector, MT5Status, SymbolInfo, TickRecord
from app.mt5.bridge_bootstrap import ensure_mac_bridge, shutdown_mac_bridge
from app.mt5.official import OfficialMT5Connector, _base_code


class BridgeMT5Connector(MT5Connector):
    """FBS/MT5 market data via MetaTrader 5.app (Wine) + rpyc on macOS."""

    def __init__(self) -> None:
        self._inner: OfficialMT5Connector | None = None

    def _ensure_inner(self) -> OfficialMT5Connector:
        if self._inner is None:
            ensure_mac_bridge()
            self._inner = OfficialMT5Connector()
        return self._inner

    def _tag(self, status: MT5Status) -> MT5Status:
        settings = get_settings()
        status.mode = "bridge"
        details = dict(status.details or {})
        details.update(
            {
                "bridge": True,
                "bridge_host": settings.mt5_bridge_host,
                "bridge_port": settings.mt5_bridge_port,
                "research_only": True,
                "orders_disabled": True,
                "balance_hidden": True,
            }
        )
        status.details = details
        status.trade_allowed = False
        return status

    def connect(self) -> MT5Status:
        return self._tag(self._ensure_inner().connect())

    def disconnect(self) -> None:
        try:
            if self._inner is not None:
                self._inner.disconnect()
        finally:
            shutdown_mac_bridge()
            self._inner = None

    def status(self) -> MT5Status:
        if self._inner is None:
            return self._tag(MT5Status(connected=False, mode="bridge", last_error="bridge not connected"))
        return self._tag(self._inner.status())

    def discover_symbols(self, query: str | None = None) -> list[SymbolInfo]:
        """Discover symbols without per-field rpyc netref chatter.

        Walking ``symbols_get()`` attribute-by-attribute across ~500 FBS
        instruments kills the Wine-side ThreadedServer (EOFError / dropped
        listener). Prefer one ``eval`` round-trip that returns plain dicts.
        """
        inner = self._ensure_inner()
        mt5 = getattr(inner, "_mt5", None)
        if mt5 is None:
            return inner.discover_symbols(query)

        needle = (query or "").upper()
        preferred = {base.upper() for base in PREFERRED_BASES}
        raw: list[dict] = []
        if hasattr(mt5, "eval"):
            try:
                raw = list(
                    mt5.eval(
                        "["
                        "{'name': s.name, 'description': s.description or '', "
                        "'digits': int(s.digits), 'point': float(s.point), "
                        "'contract_size': float(getattr(s, 'trade_contract_size', 0) or 0), "
                        "'visible': bool(s.visible)}"
                        " for s in (mt5.symbols_get() or [])]"
                    )
                    or []
                )
            except Exception:
                raw = []

        if not raw:
            # Narrow fallback: only preferred majors via symbol_info (few RPCs).
            for base in PREFERRED_BASES:
                info = mt5.symbol_info(base)
                if info is None:
                    continue
                raw.append(
                    {
                        "name": info.name,
                        "description": info.description or "",
                        "digits": int(info.digits),
                        "point": float(info.point),
                        "contract_size": float(getattr(info, "trade_contract_size", 0) or 0),
                        "visible": bool(info.visible),
                    }
                )

        items: list[SymbolInfo] = []
        for row in raw:
            name = str(row.get("name") or "")
            description = str(row.get("description") or "")
            if needle and needle not in name.upper() and needle not in description.upper():
                continue
            # Keep preferred majors + visible instruments to bound DB size.
            if name.upper() not in preferred and not bool(row.get("visible")):
                continue
            items.append(
                SymbolInfo(
                    name=name,
                    description=description,
                    digits=int(row.get("digits") or 0),
                    point=float(row.get("point") or 0.0),
                    contract_size=float(row.get("contract_size") or 0.0),
                    visible=bool(row.get("visible")),
                    base_code=_base_code(name),
                )
            )
        return items

    def resolve_symbol(self, requested: str) -> SymbolInfo | None:
        # Avoid the official fallback that re-runs full discover_symbols.
        inner = self._ensure_inner()
        mt5 = getattr(inner, "_mt5", None)
        if mt5 is None:
            return inner.resolve_symbol(requested)

        candidates = [requested, _base_code(requested)]
        base = _base_code(requested)
        candidates.extend(f"{base}{suffix}" for suffix in SYMBOL_SUFFIXES if suffix)
        seen: set[str] = set()
        for candidate in candidates:
            key = candidate.upper()
            if not candidate or key in seen:
                continue
            seen.add(key)
            info = mt5.symbol_info(candidate)
            if info is None:
                continue
            try:
                mt5.symbol_select(info.name, True)
            except Exception:
                pass
            return SymbolInfo(
                name=info.name,
                description=info.description or "",
                digits=int(info.digits),
                point=float(info.point),
                contract_size=float(getattr(info, "trade_contract_size", 0) or 0),
                visible=True,
                base_code=_base_code(info.name),
            )
        return None

    def copy_rates_range(
        self,
        symbol: str,
        timeframe: str,
        date_from: datetime,
        date_to: datetime,
    ) -> list[CandleRecord]:
        return self._ensure_inner().copy_rates_range(symbol, timeframe, date_from, date_to)

    def copy_rates_from_pos(self, symbol: str, timeframe: str, start: int, count: int) -> list[CandleRecord]:
        return self._ensure_inner().copy_rates_from_pos(symbol, timeframe, start, count)

    def symbol_tick(self, symbol: str) -> TickRecord | None:
        return self._ensure_inner().symbol_tick(symbol)
