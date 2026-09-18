"""Unit tests for signals.forecast: training-frame construction, backtest on a
planted signal, scoring shape, the fallback index, and the auto-mode rule —
all on synthetic bg_features. See md/architecture.md §8.
"""
from __future__ import annotations

import json

import duckdb
import numpy as np
import pandas as pd
import pytest

from signals import forecast
from signals.config import ModelMode, Settings

TODAY = pd.Timestamp("2026-09-18")
YEARS = list(range(2011, 2027))
FEATURE_COLS = [
    "n_sales", "median_price", "median_ppsf", "price_yoy", "llc_share", "out_of_state_share",
    "permit_count", "permit_value", "new_construction_permits", "permit_count_yoy",
    "blight_tickets", "vacant_share", "owner_occ_share", "dist_to_hot_corridor_m",
]


def _settings(tmp_path) -> Settings:
    return Settings(_env_file=None, DATA_DIR=str(tmp_path))


def _synthetic_features(n_bg: int = 60, seed: int = 0) -> pd.DataFrame:
    """Block groups whose two-year-forward ppsf growth is driven by llc_share
    (plus noise), so a working model must rank on llc_share. llc_share is
    persistent year to year (AR(1)), the way real investor activity is, so
    the signal is recoverable from year-T features alone."""
    rng = np.random.default_rng(seed)
    rows = []
    for i in range(n_bg):
        geoid = f"bg{i:03d}"
        llc = np.empty(len(YEARS))
        llc[0] = rng.uniform(0, 1)
        for j in range(1, len(YEARS)):
            llc[j] = np.clip(0.8 * llc[j - 1] + 0.2 * rng.uniform(0, 1), 0, 1)
        growth = 0.5 * np.roll(llc, 2) + rng.normal(0, 0.08, len(YEARS))
        ppsf = 60 * np.exp(np.cumsum(growth))
        for j, year in enumerate(YEARS):
            rows.append(
                {
                    "bg_geoid": geoid,
                    "year": year,
                    "n_sales": 10,
                    "median_price": ppsf[j] * 1000,
                    "median_ppsf": ppsf[j],
                    "price_yoy": np.nan if j == 0 else np.log(ppsf[j] / ppsf[j - 1]),
                    "llc_share": llc[j],
                    "out_of_state_share": rng.uniform(0, 0.3),
                    "permit_count": np.nan if year < 2019 else rng.integers(0, 20),
                    "permit_value": np.nan if year < 2019 else rng.uniform(0, 1e6),
                    "new_construction_permits": np.nan if year < 2019 else rng.integers(0, 3),
                    "permit_count_yoy": np.nan if year < 2020 else rng.normal(0, 0.5),
                    "blight_tickets": rng.integers(0, 50),
                    "vacant_share": 0.3,
                    "owner_occ_share": 0.4,
                    "dist_to_hot_corridor_m": np.nan if year < 2020 else rng.uniform(0, 8000),
                }
            )
    return pd.DataFrame(rows)


# ---------------------------------------------------------------------------
# training frame
# ---------------------------------------------------------------------------

def test_latest_complete_year_excludes_partial_current_year():
    df = pd.DataFrame({"year": YEARS})
    assert forecast.latest_complete_year(df, TODAY) == 2025


def test_training_frame_target_math_and_bounds():
    ppsf = {y: 100.0 * (1.1 ** (y - 2011)) for y in YEARS}
    df = pd.DataFrame(
        {
            "bg_geoid": "A",
            "year": YEARS,
            "n_sales": [10] * len(YEARS),
            "median_ppsf": [ppsf[y] for y in YEARS],
            **{c: 0.0 for c in FEATURE_COLS if c not in ("n_sales", "median_ppsf")},
        }
    )
    df.loc[df["year"] == 2016, "n_sales"] = 1  # too thin to be a target endpoint
    df.loc[df["year"] == 2011, "median_ppsf"] = 5.0  # below the ppsf floor at T

    frame = forecast.build_training_frame(df, latest_year=2025)

    assert frame["year"].max() == 2023  # 2023 + 2 = 2025; nothing targets partial 2026
    row = frame.loc[frame["year"] == 2020].iloc[0]
    assert row["target"] == pytest.approx(np.log(ppsf[2022] / ppsf[2020]))
    # 2016 thin: excluded as T (2016) and as T+2 endpoint (T=2014)
    assert 2016 not in set(frame["year"])
    assert 2014 not in set(frame["year"])
    assert 2011 not in set(frame["year"])  # start price too low to be a sane base
    assert "vacant_share" not in frame.columns  # snapshot columns excluded
    assert "median_ppsf" not in frame.columns  # level columns excluded (mean-reversion trap)
    assert "llc_share" in frame.columns


# ---------------------------------------------------------------------------
# train / backtest
# ---------------------------------------------------------------------------

def test_train_recovers_planted_signal_and_writes_artifacts(tmp_path):
    settings = _settings(tmp_path)
    features = _synthetic_features()

    model, report = forecast.train(features, settings=settings, today=TODAY)

    assert report["holdout_year"] == 2023
    assert report["training_rows"] >= forecast.MIN_TRAINING_ROWS
    assert report["backtest"]["spearman"] > 0.3  # planted llc_share signal recovered
    assert report["backtest"]["mae"] < report["backtest"]["baseline_mae_predict_mean"]
    assert report["auto_mode_decision"] == "trained"
    assert set(report["fallback_index_backtest"]["spearman_by_holdout_year"]) == {"2019", "2020", "2021", "2022", "2023"}
    top_feature = next(iter(report["permutation_importance"]))
    assert top_feature == "llc_share"
    assert "vacant_share" not in report["feature_columns"]
    assert "median_ppsf" not in report["feature_columns"]

    assert (settings.models_dir / forecast.REPORT_FILENAME).exists()
    assert (settings.models_dir / forecast.MODEL_FILENAME).exists()
    reloaded = forecast.load_model(settings)
    assert reloaded.feature_columns == model.feature_columns


def test_score_shape_and_top_signals(tmp_path):
    settings = _settings(tmp_path)
    features = _synthetic_features(n_bg=40)
    model, _ = forecast.train(features, settings=settings, today=TODAY)

    scores = forecast.score(model, features, today=TODAY)

    assert len(scores) == 40
    assert scores["bg_geoid"].is_unique
    assert scores["heat_score"].between(0, 100).all()
    assert scores["heat_score"].min() == 0 and scores["heat_score"].max() == 100
    assert (scores["model_mode"] == "trained").all()
    assert (scores["confidence"] == "ok").all()  # fixture has 10 sales everywhere
    signals = json.loads(scores["top_signals"].iloc[0])
    assert len(signals) == forecast.TOP_SIGNALS_N
    assert set(signals[0]) == {"feature", "value", "z", "direction", "weight"}
    assert signals[0]["direction"] in ("up", "down")
    # ranking follows the prediction
    assert scores.sort_values("predicted_growth")["heat_score"].is_monotonic_increasing


# ---------------------------------------------------------------------------
# fallback index
# ---------------------------------------------------------------------------

def test_fallback_index_is_deterministic_and_ranks_by_weights():
    features = _synthetic_features(n_bg=30)
    year = 2025
    hot = features["year"] == year
    # make one block group extreme in the direction of every weight's sign:
    # heavy LLC buying, big permit jump, a price *dip* last year (momentum is
    # weighted negative — it reverts), right next to a hot corridor
    features.loc[hot & (features["bg_geoid"] == "bg000"), ["permit_count_yoy", "price_yoy", "llc_share", "permit_value"]] = [5.0, -2.0, 1.0, 9e6]
    features.loc[hot & (features["bg_geoid"] == "bg000"), "dist_to_hot_corridor_m"] = 0.0

    a = forecast.fallback_index(features, today=TODAY)
    b = forecast.fallback_index(features, today=TODAY)

    pd.testing.assert_frame_equal(a.drop(columns="scored_at"), b.drop(columns="scored_at"))
    assert (a["model_mode"] == "fallback").all()
    assert a.loc[a["bg_geoid"] == "bg000", "heat_score"].iloc[0] == 100
    signals = json.loads(a.loc[a["bg_geoid"] == "bg000", "top_signals"].iloc[0])
    assert {s["feature"] for s in signals} <= set(forecast.FALLBACK_WEIGHTS)


def test_recommended_mode_thresholds():
    ok = {"training_rows": 1000, "backtest": {"spearman": 0.4}}
    thin = {"training_rows": 100, "backtest": {"spearman": 0.9}}
    weak = {"training_rows": 1000, "backtest": {"spearman": 0.05}}
    nan = {"training_rows": 1000, "backtest": {"spearman": float("nan")}}
    assert forecast.recommended_mode(ok) == ModelMode.TRAINED
    assert forecast.recommended_mode(thin) == ModelMode.FALLBACK
    assert forecast.recommended_mode(weak) == ModelMode.FALLBACK
    assert forecast.recommended_mode(nan) == ModelMode.FALLBACK


def test_write_scores_round_trips_through_duckdb():
    features = _synthetic_features(n_bg=5)
    scores = forecast.fallback_index(features, today=TODAY)
    con = duckdb.connect(":memory:")

    forecast.write_scores(con, scores)

    n, mode, conf = con.execute(
        "SELECT count(*), any_value(model_mode), any_value(confidence) FROM bg_scores"
    ).fetchone()
    assert n == 5 and mode == "fallback" and conf == "ok"
    first = con.execute("SELECT top_signals->>'$[0].feature' FROM bg_scores LIMIT 1").fetchone()[0]
    assert first in forecast.FALLBACK_WEIGHTS


def test_low_confidence_flag_when_scoring_year_is_thin():
    features = _synthetic_features(n_bg=5)
    features.loc[(features["year"] == 2025) & (features["bg_geoid"] == "bg000"), "n_sales"] = 1
    scores = forecast.fallback_index(features, today=TODAY)
    by = scores.set_index("bg_geoid")["confidence"]
    assert by["bg000"] == "low"
    assert (by.drop("bg000") == "ok").all()
