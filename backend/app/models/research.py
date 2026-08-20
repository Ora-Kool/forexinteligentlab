from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import DateTime, Float, ForeignKey, Index, Integer, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.types import JSON

from app.core.tenant import current_workspace_id
from app.database.session import Base


class ResearchExperiment(Base):
    __tablename__ = "research_experiments"
    __table_args__ = (
        UniqueConstraint("workspace_id", "code", name="uq_research_experiment_ws_code"),
        Index("ix_research_experiment_symbol_tf", "workspace_id", "symbol", "timeframe"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    workspace_id: Mapped[int] = mapped_column(Integer, default=current_workspace_id, index=True)
    code: Mapped[str] = mapped_column(String(80))
    strategy_name: Mapped[str] = mapped_column(String(120), default="Triple barrier logistic")
    symbol: Mapped[str] = mapped_column(String(64), index=True)
    timeframe: Mapped[str] = mapped_column(String(8), index=True)
    target_version: Mapped[str] = mapped_column(String(40), default="triple_barrier_v1")
    feature_version: Mapped[str] = mapped_column(String(40), default="causal_features_v1")
    evaluator_version: Mapped[str] = mapped_column(String(40), default="purged_walk_forward_v1")
    model_family: Mapped[str] = mapped_column(String(64), default="LogisticRegression")
    dataset_version: Mapped[str] = mapped_column(String(80), default="")
    status: Mapped[str] = mapped_column(String(32), default="PENDING", index=True)
    parameters: Mapped[dict] = mapped_column(JSONB().with_variant(JSON, "sqlite"), default=dict)
    metrics: Mapped[dict | None] = mapped_column(JSONB().with_variant(JSON, "sqlite"), nullable=True)
    error: Mapped[str] = mapped_column(Text, default="")
    train_start: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    train_end: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    holdout_start: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    holdout_end: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(UTC))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class ResearchFold(Base):
    __tablename__ = "research_folds"
    __table_args__ = (
        UniqueConstraint("experiment_id", "fold_index", name="uq_research_fold_experiment_index"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    experiment_id: Mapped[int] = mapped_column(
        ForeignKey("research_experiments.id", ondelete="CASCADE"),
        index=True,
    )
    fold_index: Mapped[int] = mapped_column(Integer)
    train_start: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    train_end: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    validation_start: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    validation_end: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    threshold: Mapped[float | None] = mapped_column(Float, nullable=True)
    train_samples: Mapped[int] = mapped_column(Integer, default=0)
    validation_samples: Mapped[int] = mapped_column(Integer, default=0)
    signals: Mapped[int] = mapped_column(Integer, default=0)
    metrics: Mapped[dict] = mapped_column(JSONB().with_variant(JSON, "sqlite"), default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(UTC))
