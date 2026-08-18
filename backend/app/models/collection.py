from datetime import UTC, datetime

from sqlalchemy import DateTime, Float, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.core.tenant import current_workspace_id
from app.database.session import Base


class CollectionJob(Base):
    __tablename__ = "collection_jobs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    workspace_id: Mapped[int] = mapped_column(Integer, default=current_workspace_id, index=True)
    kind: Mapped[str] = mapped_column(String(32), default="historical_import")
    symbol: Mapped[str] = mapped_column(String(64), index=True)
    timeframe: Mapped[str] = mapped_column(String(8))
    start_date: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    end_date: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    status: Mapped[str] = mapped_column(String(24), default="pending", index=True)
    candles_imported: Mapped[int] = mapped_column(Integer, default=0)
    candles_requested: Mapped[int] = mapped_column(Integer, default=0)
    duplicate_candles: Mapped[int] = mapped_column(Integer, default=0)
    missing_candles: Mapped[int] = mapped_column(Integer, default=0)
    first_timestamp: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_timestamp: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    duration_seconds: Mapped[float] = mapped_column(Float, default=0.0)
    error: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(UTC))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class CollectionStatus(Base):
    __tablename__ = "collection_status"
    __table_args__ = (UniqueConstraint("workspace_id", "symbol", "timeframe", name="uq_status_ws_symbol_tf"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    workspace_id: Mapped[int] = mapped_column(Integer, default=current_workspace_id, index=True)
    symbol: Mapped[str] = mapped_column(String(64), index=True)
    timeframe: Mapped[str] = mapped_column(String(8))
    last_candle: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    candles_collected: Mapped[int] = mapped_column(Integer, default=0)
    collection_rate: Mapped[str] = mapped_column(String(32), default="")
    status: Mapped[str] = mapped_column(String(24), default="IDLE")
    last_error: Mapped[str] = mapped_column(Text, default="")
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(UTC))
