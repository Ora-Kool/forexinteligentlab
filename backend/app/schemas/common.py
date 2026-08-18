from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class ORMModel(BaseModel):
    model_config = ConfigDict(from_attributes=True)


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"


class LoginRequest(BaseModel):
    username: str
    password: str


class HealthResponse(BaseModel):
    status: str
    app: str
    mt5: str
    collector: str
    database: str
    last_data: datetime | None
    mt5_mode: str
    mt5_error: str
    disclaimer: str


class SymbolOut(ORMModel):
    name: str
    display_name: str
    base_code: str
    description: str
    digits: int
    visible: bool


class MonitorIn(BaseModel):
    symbol: str
    timeframe: str = Field(pattern="^(M1|M5|M15|M30|H1|H4|D1)$")
    enabled: bool = True


class CandleOut(ORMModel):
    symbol: str
    timeframe: str
    timestamp: datetime
    open: float
    high: float
    low: float
    close: float
    bid: float | None
    ask: float | None
    spread: float | None
    tick_volume: int
    real_volume: int


class ImportRequest(BaseModel):
    symbol: str
    timeframe: str = Field(pattern="^(M1|M5|M15|M30|H1|H4|D1)$")
    start: datetime
    end: datetime


class ImportJobOut(ORMModel):
    id: int
    symbol: str
    timeframe: str
    status: str
    candles_imported: int
    candles_requested: int
    duplicate_candles: int
    missing_candles: int
    first_timestamp: datetime | None
    last_timestamp: datetime | None
    duration_seconds: float
    error: str


class TrainRequest(BaseModel):
    symbol: str
    timeframe: str = Field(pattern="^(M1|M5|M15|M30|H1|H4|D1)$")
    start: datetime | None = None
    end: datetime | None = None


class BacktestRequest(BaseModel):
    symbol: str
    timeframe: str = Field(pattern="^(M1|M5|M15|M30|H1|H4|D1)$")
    start: datetime
    end: datetime
    min_probability: float = Field(default=0.65, ge=0.5, le=1.0)
    spread_cost_pips: float = Field(default=0.8, ge=0)
    transaction_cost_pips: float = Field(default=0.2, ge=0)
    model_version: str | None = None


class AgentCandleIn(BaseModel):
    symbol: str
    timeframe: str
    timestamp: datetime
    open: float
    high: float
    low: float
    close: float
    bid: float | None = None
    ask: float | None = None
    spread: float | None = None
    tick_volume: int = 0
    real_volume: int = 0


class AgentIngestRequest(BaseModel):
    status: dict | None = None
    candles: list[AgentCandleIn] = Field(default_factory=list)
