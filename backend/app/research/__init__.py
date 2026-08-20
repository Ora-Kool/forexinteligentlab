"""Cost-aware, reproducible strategy research.

This package evaluates paper hypotheses only. It has no execution APIs.
"""

from app.research.config import ResearchConfig
from app.research.evaluator import run_walk_forward_experiment
from app.research.targets import build_triple_barrier_table

__all__ = ["ResearchConfig", "build_triple_barrier_table", "run_walk_forward_experiment"]
