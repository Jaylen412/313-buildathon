"""Read-side queries for the API. Pure functions over a DuckDB connection so
api.py stays routing and tests can point them at an in-memory database.

Public routes (blocks) never touch parcel rows except to derive a
block-group neighborhood name; household data lives in vulnerability.py
behind the org token (md/architecture.md §6).
"""
from __future__ import annotations

import json
from pathlib import Path

import duckdb

from signals.forecast import SIGNAL_LABELS

TREND_COLUMNS = [
    "n_sales", "median_ppsf", "median_price", "llc_share", "permit_count",
    "permit_value", "blight_tickets",
]


class NotScoredError(RuntimeError):
    """bg_scores is missing or empty — `signals train` has not been run."""


def _table_exists(con: duckdb.DuckDBPyConnection, name: str) -> bool:
    return con.execute(
        "SELECT count(*) FROM information_schema.tables WHERE table_name = ?", [name]
    ).fetchone()[0] > 0


def scores_stamp(con: duckdb.DuckDBPyConnection) -> str | None:
    """Cache key for anything derived from bg_scores; None if not scored."""
    if not _table_exists(con, "bg_scores"):
        return None
    row = con.execute("SELECT max(scored_at), count(*) FROM bg_scores").fetchone()
    if not row or row[1] == 0:
        return None
    return f"{row[0].isoformat()}:{row[1]}"


def block_neighborhoods(con: duckdb.DuckDBPyConnection) -> dict[str, str]:
    """Most common parcel `neighborhood` per block group — a display name
    for a 12-digit GEOID."""
    if not (_table_exists(con, "parcel_geo") and _table_exists(con, "raw_parcels")):
        return {}
    rows = con.execute(
        """
        WITH counts AS (
            SELECT g.bg_geoid, p.neighborhood, count(*) AS n,
                   row_number() OVER (PARTITION BY g.bg_geoid ORDER BY count(*) DESC) AS rn
            FROM parcel_geo g JOIN raw_parcels p USING (parcel_id)
            WHERE g.bg_geoid IS NOT NULL AND p.neighborhood IS NOT NULL AND p.neighborhood != ''
            GROUP BY 1, 2
        )
        SELECT bg_geoid, neighborhood FROM counts WHERE rn = 1
        """
    ).fetchall()
    return {geoid: name for geoid, name in rows}


def _label_signals(raw: str | list | None) -> list[dict]:
    signals = json.loads(raw) if isinstance(raw, str) else (raw or [])
    for s in signals:
        s["label"] = SIGNAL_LABELS.get(s["feature"], s["feature"])
    return signals


def all_scores(con: duckdb.DuckDBPyConnection) -> dict[str, dict]:
    if scores_stamp(con) is None:
        raise NotScoredError("no scores: run `uv run signals train`")
    rows = con.execute(
        "SELECT bg_geoid, heat_score, predicted_growth, confidence, top_signals::VARCHAR, "
        "model_version, model_mode, scored_at FROM bg_scores"
    ).fetchall()
    out = {}
    for geoid, heat, growth, conf, signals, version, mode, scored_at in rows:
        out[geoid] = {
            "bg_geoid": geoid,
            "heat_score": int(heat),
            "predicted_growth": float(growth) if growth is not None else None,
            "confidence": conf,
            "top_signals": _label_signals(signals),
            "model_version": version,
            "model_mode": mode,
            "scored_at": scored_at.isoformat(),
        }
    return out


def blocks_feature_collection(con: duckdb.DuckDBPyConnection, geojson_path: Path) -> dict:
    """Public map payload: the cached block-group polygons joined to scores.
    Block groups with polygons but no score (shouldn't happen after a full
    run) are included with heat_score=null so the map still draws them."""
    if not geojson_path.exists():
        raise FileNotFoundError(f"{geojson_path} missing: run `uv run signals features`")
    scores = all_scores(con)
    names = block_neighborhoods(con)
    collection = json.loads(geojson_path.read_text())
    for feature in collection["features"]:
        geoid = feature["properties"]["bg_geoid"]
        s = scores.get(geoid)
        feature["properties"] = {
            "bg_geoid": geoid,
            "neighborhood": names.get(geoid),
            "heat_score": s["heat_score"] if s else None,
            "confidence": s["confidence"] if s else None,
            "top_signals": s["top_signals"] if s else [],
            "model_mode": s["model_mode"] if s else None,
        }
    return collection


def block_trend(con: duckdb.DuckDBPyConnection, geoid: str) -> dict:
    """Per-year series for the drawer, oldest first. Partial current year is
    included but flagged so the UI can draw it differently."""
    if not _table_exists(con, "bg_features"):
        return {"years": [], "series": {}, "partial_year": None}
    cols = ", ".join(TREND_COLUMNS)
    rows = con.execute(
        f"SELECT year, {cols} FROM bg_features WHERE bg_geoid = ? ORDER BY year", [geoid]
    ).fetchall()
    years = [int(r[0]) for r in rows]
    series = {
        col: [None if r[i + 1] is None or r[i + 1] != r[i + 1] else float(r[i + 1]) for r in rows]
        for i, col in enumerate(TREND_COLUMNS)
    }
    from datetime import date

    partial = date.today().year if years and years[-1] == date.today().year else None
    return {"years": years, "series": series, "partial_year": partial}


def block_detail(con: duckdb.DuckDBPyConnection, geoid: str, report: dict | None) -> dict | None:
    scores = all_scores(con)
    s = scores.get(geoid)
    if s is None:
        return None
    names = block_neighborhoods(con)
    if s["model_mode"] == "fallback":
        footnote = "weighted index (fallback) — transparent, sign-checked weights"
    elif report:
        bt = report["backtest"]
        footnote = (
            f"model {s['model_version']} · backtest on {report['holdout_year']}: "
            f"Spearman ρ = {bt['spearman']:.2f}, R² = {bt['r2']:.2f}"
        )
    else:
        footnote = f"model {s['model_version']}"
    return {
        **s,
        "neighborhood": names.get(geoid),
        "trend": block_trend(con, geoid),
        "backtest_summary": footnote,
    }
