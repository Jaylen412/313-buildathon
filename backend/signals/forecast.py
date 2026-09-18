"""Train / backtest / score the block-group heat score, with a deterministic
weighted-index fallback when training data is thin (spec non-negotiable:
CLAUDE.md "Non-negotiable design constraints").

Contract (md/architecture.md §6):
    train(features) -> (ForecastModel, backtest_report)   # writes data/models/*
    score(model, features) -> pd.DataFrame                # bg_scores rows
    fallback_index(features) -> pd.DataFrame              # same shape, model_mode='fallback'
    recommended_mode(report) -> ModelMode                 # the MODEL_MODE=auto rule
    write_scores(con, scores)                             # -> bg_scores table

Target: log(median_ppsf[T+2]) - log(median_ppsf[T]) per block group, i.e. the
two-year forward change in arm's-length price per square foot. Heat score is
the city-wide percentile rank of the prediction. Every score carries its top
three signals (feature z-score vs the city that year, weighted by global
permutation importance) so an organizer can defend it out loud.

Snapshot features (vacant_share, owner_occ_share, out_of_state_share)
describe the parcel file *today*; feeding them to a model trained on past
windows would leak the present into the backtest, so the trained model
excludes them. They stay in bg_features for vulnerability.py.

Price *level* features (median_ppsf, median_price) are excluded too. The
first real-data run (2026-09-18) kept them and the model's top signal became
"median_ppsf low": it ranked $8-22/sqft block groups with a falling prior
year as the hottest in the city, because a cheap, noisy market has the
largest percentage rebounds. That is mean reversion, not investment
pressure. Without levels the model has to rank on momentum, LLC buying,
permits, blight and corridor proximity — the signals the product claims.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timezone

import joblib
import numpy as np
import pandas as pd
from sklearn.ensemble import HistGradientBoostingRegressor
from sklearn.inspection import permutation_importance

from signals.config import ModelMode, Settings, get_settings

MODEL_VERSION = "hgb-v1"
FALLBACK_VERSION = "index-v1"
HORIZON_YEARS = 2
MIN_SALES_FOR_TARGET = 5
MIN_PPSF_FOR_TARGET = 20.0
"""log ratios of near-zero land-value sales are noise, not growth."""
MIN_SALES_FOR_CONFIDENCE = 3
MIN_TRAINING_ROWS = 500
MIN_BACKTEST_SPEARMAN = 0.2
TOP_SIGNALS_N = 3

# Fallback weights — published, sign-checked on real data (md/architecture.md §6).
# The original draft weighted one-year price momentum +0.25. Backtested on
# five holdout years (2019-2023) that index was *anti*-predictive (Spearman
# -0.13 to -0.22 with realized two-year growth): in block groups with 5-10
# sales a year, last year's median spike is mostly composition noise and
# reverts. Sustained LLC buying is the strongest single positive signal.
# This weighting keeps every signal the product names, with momentum
# discounted: Spearman +0.13 to +0.32 on the same five years.
FALLBACK_WEIGHTS: dict[str, float] = {
    "llc_share": 0.35,
    "price_yoy": -0.25,
    "permit_count_yoy": 0.15,
    "permit_value": 0.10,
    "dist_to_hot_corridor_m": -0.15,
}

# Plain-language labels for top_signals, for the drawer and the brief. The
# direction ("up"/"down") is the block vs the city that year; these say what
# the feature *is*, the UI adds the direction.
SIGNAL_LABELS: dict[str, str] = {
    "price_yoy": "sale prices vs. the year before (one-year swings mostly revert in thin markets)",
    "llc_share": "share of sales bought by LLCs / investors",
    "out_of_state_share": "share of owners with an out-of-state mailing address",
    "permit_count": "building permits issued",
    "permit_value": "dollar value of building permits",
    "new_construction_permits": "new-construction permits",
    "permit_count_yoy": "change in permit count vs. the year before",
    "blight_tickets": "blight tickets issued",
    "n_sales": "number of arm's-length sales",
    "dist_to_hot_corridor_m": "distance to the nearest high-permit corridor",
    "median_ppsf": "median sale price per square foot",
    "median_price": "median sale price",
    "vacant_share": "share of parcels that are vacant",
    "owner_occ_share": "share of parcels with a homestead exemption",
}

SNAPSHOT_COLUMNS = ["vacant_share", "owner_occ_share", "out_of_state_share"]
LEVEL_COLUMNS = ["median_ppsf", "median_price"]
NON_FEATURE_COLUMNS = ["bg_geoid", "year"]
EXCLUDED_COLUMNS = NON_FEATURE_COLUMNS + SNAPSHOT_COLUMNS + LEVEL_COLUMNS

MODEL_FILENAME = "model.joblib"
REPORT_FILENAME = "backtest_report.json"


@dataclass
class ForecastModel:
    estimator: HistGradientBoostingRegressor
    feature_columns: list[str]
    importances: dict[str, float]
    """Permutation importance on the holdout window, clipped at 0."""
    version: str = MODEL_VERSION


# ---------------------------------------------------------------------------
# training frame
# ---------------------------------------------------------------------------

def feature_columns(features: pd.DataFrame) -> list[str]:
    return [c for c in features.columns if c not in EXCLUDED_COLUMNS]


def latest_complete_year(features: pd.DataFrame, today: pd.Timestamp | None = None) -> int:
    """The current calendar year is partial (features are counts), so the
    newest year we score on or use as a target is the one before it."""
    today = today or pd.Timestamp.now()
    return min(int(features["year"].max()), today.year - 1)


def build_training_frame(features: pd.DataFrame, latest_year: int) -> pd.DataFrame:
    """One row per (bg_geoid, T) with target = log ppsf[T+H] - log ppsf[T].
    Requires >= MIN_SALES_FOR_TARGET sales at both ends (a median of one
    sale is noise), a starting price >= MIN_PPSF_FOR_TARGET (log ratios of
    near-zero land sales are noise), and T+H <= latest_year (no partial-year
    targets)."""
    cols = feature_columns(features)
    f = features.sort_values(["bg_geoid", "year"])
    future = f[["bg_geoid", "year", "median_ppsf", "n_sales"]].rename(
        columns={"median_ppsf": "ppsf_future", "n_sales": "n_sales_future"}
    )
    future = future.assign(year=future["year"] - HORIZON_YEARS)
    frame = f.merge(future, on=["bg_geoid", "year"], how="inner")
    ok = (
        (frame["year"] + HORIZON_YEARS <= latest_year)
        & (frame["n_sales"] >= MIN_SALES_FOR_TARGET)
        & (frame["n_sales_future"] >= MIN_SALES_FOR_TARGET)
        & (frame["median_ppsf"] >= MIN_PPSF_FOR_TARGET)
        & (frame["ppsf_future"] > 0)
    )
    frame = frame.loc[ok].copy()
    frame["target"] = np.log(frame["ppsf_future"]) - np.log(frame["median_ppsf"])
    return frame[["bg_geoid", "year", *cols, "target"]].reset_index(drop=True)


# ---------------------------------------------------------------------------
# train / backtest
# ---------------------------------------------------------------------------

def _fit(X: pd.DataFrame, y: pd.Series) -> HistGradientBoostingRegressor:
    est = HistGradientBoostingRegressor(
        max_iter=600,
        learning_rate=0.04,
        max_depth=4,
        min_samples_leaf=25,
        l2_regularization=1.0,
        # sklearn only auto-enables early stopping above 10k rows; we have ~5k,
        # and without it the model keeps fitting noise features.
        early_stopping=True,
        validation_fraction=0.15,
        n_iter_no_change=25,
        random_state=0,
    )
    return est.fit(X, y)


def recommended_mode(report: dict) -> ModelMode:
    """The MODEL_MODE=auto rule: fall back to the weighted index when the
    training set is thin or the backtest can't rank block groups."""
    rows_ok = report["training_rows"] >= MIN_TRAINING_ROWS
    spearman = report["backtest"]["spearman"]
    rank_ok = spearman is not None and not np.isnan(spearman) and spearman >= MIN_BACKTEST_SPEARMAN
    return ModelMode.TRAINED if (rows_ok and rank_ok) else ModelMode.FALLBACK


def _index_spearman(frame: pd.DataFrame, year: int, weights: dict[str, float]) -> float | None:
    """Backtest the transparent index the same way as the model: index from
    year-T features vs the realized target, within one holdout year."""
    te = frame.loc[frame["year"] == year]
    if len(te) < 10:
        return None
    z = _zscores(te[list(weights)])
    idx = sum(z[c].fillna(0) * w for c, w in weights.items())
    return float(pd.Series(idx.to_numpy()).corr(pd.Series(te["target"].to_numpy()), method="spearman"))


def train(
    features: pd.DataFrame,
    settings: Settings | None = None,
    today: pd.Timestamp | None = None,
) -> tuple[ForecastModel, dict]:
    """Backtest on the latest complete window (train on T < holdout year,
    evaluate on T == holdout year), then refit on every row for scoring.
    Writes data/models/backtest_report.json and data/models/model.joblib."""
    settings = settings or get_settings()
    latest = latest_complete_year(features, today)
    frame = build_training_frame(features, latest)
    cols = feature_columns(features)
    if frame.empty:
        raise ValueError("forecast.train: no rows have a defined target")

    holdout_year = int(frame["year"].max())
    train_mask = frame["year"] < holdout_year
    if train_mask.sum() == 0:
        raise ValueError("forecast.train: only one target year available, cannot hold one out")

    X_tr, y_tr = frame.loc[train_mask, cols], frame.loc[train_mask, "target"]
    X_ho, y_ho = frame.loc[~train_mask, cols], frame.loc[~train_mask, "target"]

    backtest_model = _fit(X_tr, y_tr)
    pred = backtest_model.predict(X_ho)
    mae = float(np.mean(np.abs(pred - y_ho.to_numpy())))
    baseline_mae = float(np.mean(np.abs(y_ho.to_numpy() - y_tr.mean())))
    r2 = float(backtest_model.score(X_ho, y_ho))
    spearman = float(pd.Series(pred).corr(pd.Series(y_ho.to_numpy()), method="spearman"))

    pi = permutation_importance(
        backtest_model, X_ho, y_ho, n_repeats=10, random_state=0,
        scoring="neg_mean_absolute_error",
    )
    importances = {c: float(max(v, 0.0)) for c, v in zip(cols, pi.importances_mean)}

    final = _fit(frame[cols], frame["target"])
    model = ForecastModel(final, cols, importances)

    report = {
        "model_version": MODEL_VERSION,
        "trained_at": datetime.now(timezone.utc).isoformat(),
        "target": f"log(median_ppsf[T+{HORIZON_YEARS}]) - log(median_ppsf[T])",
        "latest_complete_year": latest,
        "holdout_year": holdout_year,
        "train_years": [int(frame.loc[train_mask, "year"].min()), int(frame.loc[train_mask, "year"].max())],
        "training_rows": int(train_mask.sum()),
        "holdout_rows": int((~train_mask).sum()),
        "total_rows": int(len(frame)),
        "backtest": {"mae": mae, "baseline_mae_predict_mean": baseline_mae, "r2": r2, "spearman": spearman},
        "permutation_importance": dict(sorted(importances.items(), key=lambda kv: -kv[1])),
        "fallback_index_backtest": {
            "weights": FALLBACK_WEIGHTS,
            "spearman_by_holdout_year": {
                str(y): _index_spearman(frame, y, FALLBACK_WEIGHTS)
                for y in range(holdout_year - 4, holdout_year + 1)
            },
        },
        "feature_columns": cols,
        "excluded_snapshot_columns": SNAPSHOT_COLUMNS,
        "excluded_level_columns": LEVEL_COLUMNS,
        "target_filters": {"min_sales_each_end": MIN_SALES_FOR_TARGET, "min_start_ppsf": MIN_PPSF_FOR_TARGET},
        "thresholds": {"min_training_rows": MIN_TRAINING_ROWS, "min_backtest_spearman": MIN_BACKTEST_SPEARMAN},
    }
    report["auto_mode_decision"] = recommended_mode(report).value

    settings.models_dir.mkdir(parents=True, exist_ok=True)
    (settings.models_dir / REPORT_FILENAME).write_text(json.dumps(report, indent=2))
    joblib.dump(model, settings.models_dir / MODEL_FILENAME)
    return model, report


def load_model(settings: Settings | None = None) -> ForecastModel:
    settings = settings or get_settings()
    return joblib.load(settings.models_dir / MODEL_FILENAME)


def load_report(settings: Settings | None = None) -> dict:
    settings = settings or get_settings()
    return json.loads((settings.models_dir / REPORT_FILENAME).read_text())


# ---------------------------------------------------------------------------
# scoring
# ---------------------------------------------------------------------------

def _zscores(X: pd.DataFrame) -> pd.DataFrame:
    std = X.std(ddof=0).replace(0, np.nan)
    return (X - X.mean()) / std


def _top_signals(z_row: pd.Series, values: pd.Series, weights: dict[str, float]) -> list[dict]:
    """Top-N features by |z| x |weight|. `direction` is where the block sits
    relative to the city that year (up = above average)."""
    usable = {c: abs(z_row[c]) * abs(weights.get(c, 0.0)) for c in z_row.index if pd.notna(z_row[c])}
    if not usable:
        return []
    if sum(usable.values()) == 0:  # degenerate weights: rank by |z| alone
        usable = {c: abs(z_row[c]) for c in usable}
    top = sorted(usable, key=usable.get, reverse=True)[:TOP_SIGNALS_N]
    return [
        {
            "feature": c,
            "value": float(values[c]),
            "z": round(float(z_row[c]), 3),
            "direction": "up" if z_row[c] >= 0 else "down",
            "weight": round(float(weights.get(c, 0.0)), 4),
        }
        for c in top
    ]


def _assemble(
    rows: pd.DataFrame, predicted: np.ndarray, z: pd.DataFrame,
    weights: dict[str, float], version: str, mode: ModelMode,
) -> pd.DataFrame:
    n = len(rows)
    ranks = pd.Series(predicted).rank(method="average")
    heat = np.zeros(n, dtype=int) if n < 2 else np.rint((ranks - 1) / (n - 1) * 100).astype(int).to_numpy()
    signals = [
        json.dumps(_top_signals(z.iloc[i], rows.iloc[i][z.columns], weights)) for i in range(n)
    ]
    # A score built on <3 sales that year is a guess; say so rather than hide it.
    n_sales = rows["n_sales"].fillna(0).to_numpy() if "n_sales" in rows else np.full(n, np.nan)
    confidence = np.where(n_sales >= MIN_SALES_FOR_CONFIDENCE, "ok", "low")
    return pd.DataFrame(
        {
            "bg_geoid": rows["bg_geoid"].to_numpy(),
            "heat_score": heat,
            "predicted_growth": predicted.astype(float),
            "confidence": confidence,
            "top_signals": signals,
            "model_version": version,
            "model_mode": mode.value,
            "scored_at": datetime.now(timezone.utc),
        }
    )


def score(
    model: ForecastModel, features: pd.DataFrame, year: int | None = None,
    today: pd.Timestamp | None = None,
) -> pd.DataFrame:
    """Predict two-year growth for every block group from its latest
    complete year of features; heat_score = city-wide percentile (0-100)."""
    year = year or latest_complete_year(features, today)
    rows = features.loc[features["year"] == year].reset_index(drop=True)
    X = rows[model.feature_columns]
    predicted = model.estimator.predict(X)
    return _assemble(rows, predicted, _zscores(X), model.importances, model.version, ModelMode.TRAINED)


def fallback_index(
    features: pd.DataFrame, year: int | None = None, today: pd.Timestamp | None = None,
) -> pd.DataFrame:
    """Transparent weighted z-score index over FALLBACK_WEIGHTS. Missing
    values contribute 0. Same output shape as score()."""
    year = year or latest_complete_year(features, today)
    rows = features.loc[features["year"] == year].reset_index(drop=True)
    X = rows[list(FALLBACK_WEIGHTS)]
    z = _zscores(X)
    index = sum(z[c].fillna(0) * w for c, w in FALLBACK_WEIGHTS.items())
    return _assemble(rows, index.to_numpy(), z, FALLBACK_WEIGHTS, FALLBACK_VERSION, ModelMode.FALLBACK)


def write_scores(con, scores: pd.DataFrame) -> None:
    con.register("_bg_scores_tmp", scores)
    try:
        con.execute(
            "CREATE OR REPLACE TABLE bg_scores AS "
            "SELECT bg_geoid, heat_score, predicted_growth, confidence, "
            "top_signals::JSON AS top_signals, model_version, model_mode, scored_at "
            "FROM _bg_scores_tmp"
        )
    finally:
        con.unregister("_bg_scores_tmp")
