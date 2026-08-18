from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime


@dataclass
class SymbolInfo:
    name: str
    description: str = ""
    digits: int = 5
    point: float = 0.00001
    contract_size: float = 100000.0
    visible: bool = True
    base_code: str = ""


@dataclass
class TickRecord:
    symbol: str
    timestamp: datetime
    bid: float
    ask: float
    last: float
    volume: int = 0


@dataclass
class CandleRecord:
    symbol: str
    timeframe: str
    timestamp: datetime
    open: float
    high: float
    low: float
    close: float
    tick_volume: int = 0
    real_volume: int = 0
    spread: float | None = None
    bid: float | None = None
    ask: float | None = None


@dataclass
class MT5Status:
    connected: bool
    mode: str
    terminal: str = ""
    server: str = ""
    login: int | None = None
    company: str = ""
    trade_allowed: bool = False
    last_error: str = ""
    symbols_available: int = 0
    details: dict = field(default_factory=dict)


class MT5ConnectionError(RuntimeError):
    pass


class MT5Connector(ABC):
    """Abstract market-data source. Implementations must never place orders."""

    @abstractmethod
    def connect(self) -> MT5Status:
        raise NotImplementedError

    @abstractmethod
    def disconnect(self) -> None:
        raise NotImplementedError

    @abstractmethod
    def status(self) -> MT5Status:
        raise NotImplementedError

    @abstractmethod
    def discover_symbols(self, query: str | None = None) -> list[SymbolInfo]:
        raise NotImplementedError

    @abstractmethod
    def resolve_symbol(self, requested: str) -> SymbolInfo | None:
        raise NotImplementedError

    @abstractmethod
    def copy_rates_range(
        self,
        symbol: str,
        timeframe: str,
        date_from: datetime,
        date_to: datetime,
    ) -> list[CandleRecord]:
        raise NotImplementedError

    @abstractmethod
    def copy_rates_from_pos(self, symbol: str, timeframe: str, start: int, count: int) -> list[CandleRecord]:
        raise NotImplementedError

    @abstractmethod
    def symbol_tick(self, symbol: str) -> TickRecord | None:
        raise NotImplementedError
