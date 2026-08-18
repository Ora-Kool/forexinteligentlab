from datetime import UTC, datetime

from sqlalchemy import Boolean, DateTime, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.core.tenant import current_workspace_id
from app.database.session import Base


class Symbol(Base):
    __tablename__ = "symbols"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    display_name: Mapped[str] = mapped_column(String(64))
    base_code: Mapped[str] = mapped_column(String(32), index=True)
    description: Mapped[str] = mapped_column(String(255), default="")
    digits: Mapped[int] = mapped_column(Integer, default=5)
    point: Mapped[float] = mapped_column(default=0.00001)
    contract_size: Mapped[float] = mapped_column(default=100000.0)
    visible: Mapped[bool] = mapped_column(Boolean, default=True)
    discovered_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(UTC))


class MonitoredInstrument(Base):
    __tablename__ = "monitored_instruments"
    __table_args__ = (UniqueConstraint("workspace_id", "symbol", "timeframe", name="uq_monitored_ws_symbol_tf"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    workspace_id: Mapped[int] = mapped_column(Integer, default=current_workspace_id, index=True)
    symbol: Mapped[str] = mapped_column(String(64), index=True)
    timeframe: Mapped[str] = mapped_column(String(8), index=True)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(UTC))
