"""Train / backtest / score the block-group heat score, with a deterministic
weighted-index fallback when training data is thin (spec non-negotiable:
md/CLAUDE.md "Non-negotiable design constraints").

Contract (md/architecture.md §6):
    train(features) -> (Model, backtest_report: dict)
    score(model, features) -> pd.DataFrame        # writes bg_scores
    fallback_index(features) -> pd.DataFrame      # same output shape, model_mode='fallback'

Build order milestone: step 4 (Forecast). Not yet implemented.
"""
from __future__ import annotations

from typing import Any

import pandas as pd

# Fallback weights (published, not tuned) — see md/architecture.md §6.
FALLBACK_WEIGHTS: dict[str, float] = {
    "permit_count_yoy": 0.25,
    "price_yoy": 0.25,
    "llc_share": 0.20,
    "permit_value": 0.15,
    "dist_to_hot_corridor_m": -0.15,
}


def train(features: pd.DataFrame) -> tuple[Any, dict]:
    """sklearn.ensemble.HistGradientBoostingRegressor; target = 2-year forward
    change in log median ppsf. Holds out the latest window as backtest.
    Writes data/models/backtest_report.json (MAE, R2, Spearman rho, feature
    importances, training row count)."""
    raise NotImplementedError("forecast.train: see md/architecture.md §6")


def score(model: Any, features: pd.DataFrame) -> pd.DataFrame:
    """Predict on the latest year, percentile-rank to heat_score (0-100), and
    compute top_signals as the block's top-3 feature z-scores weighted by
    global permutation importance."""
    raise NotImplementedError("forecast.score: see md/architecture.md §6")


def fallback_index(features: pd.DataFrame) -> pd.DataFrame:
    """Transparent weighted z-score index using FALLBACK_WEIGHTS. Same output
    shape as score(); model_mode='fallback'. Used when MODEL_MODE=fallback, or
    under MODEL_MODE=auto when training rows < 500 or backtest Spearman < 0.2."""
    raise NotImplementedError("forecast.fallback_index: see md/architecture.md §6")
