from __future__ import annotations

from dataclasses import asdict, dataclass, field


@dataclass(frozen=True)
class ResearchConfig:
    """Fully reproducible parameters for the first research engine."""

    tp_atr: float = 1.5
    sl_atr: float = 1.0
    timeout_bars: int = 12
    spread_cost_pips: float = 0.8
    transaction_cost_pips: float = 0.2
    minimum_edge_pips: float = 0.5
    ambiguity_policy: str = "pessimistic"
    folds: int = 4
    min_train_bars: int = 1000
    validation_bars: int = 500
    tuning_ratio: float = 0.2
    minimum_tuning_signals: int = 30
    minimum_validation_signals: int = 50
    thresholds: tuple[float, ...] = field(
        default=(0.50, 0.55, 0.60, 0.65, 0.70, 0.75, 0.80, 0.85)
    )
    bootstrap_samples: int = 1000
    random_seed: int = 42

    def validate(self) -> None:
        if self.tp_atr <= 0 or self.sl_atr <= 0:
            raise ValueError("TP and SL ATR multipliers must be positive.")
        if self.timeout_bars < 1:
            raise ValueError("Timeout must be at least one bar.")
        if self.ambiguity_policy not in {"pessimistic", "exclude"}:
            raise ValueError("Ambiguity policy must be pessimistic or exclude.")
        if self.folds < 1:
            raise ValueError("At least one walk-forward fold is required.")
        if self.min_train_bars < 100:
            raise ValueError("Minimum training bars must be at least 100.")
        if self.validation_bars < 50:
            raise ValueError("Validation bars must be at least 50.")
        if not 0.1 <= self.tuning_ratio <= 0.4:
            raise ValueError("Tuning ratio must be between 0.1 and 0.4.")
        if any(value < 0.5 or value > 0.99 for value in self.thresholds):
            raise ValueError("Thresholds must be between 0.5 and 0.99.")

    @property
    def configured_cost_pips(self) -> float:
        return self.spread_cost_pips + self.transaction_cost_pips

    def to_dict(self) -> dict:
        payload = asdict(self)
        payload["thresholds"] = list(self.thresholds)
        return payload
