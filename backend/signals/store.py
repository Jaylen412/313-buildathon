"""Read-side queries for the API. Pure functions over a DuckDB connection so
api.py stays routing and tests can point them at an in-memory database.

Public routes (blocks) never touch parcel rows except to derive a
block-group neighborhood name; household data lives in vulnerability.py
behind the org token (md/architecture.md §6).
"""
from __future__ import annotations

import json
import re
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
                   row_number() OVER (PARTITION BY g.bg_geoid ORDER BY count(*) DESC, p.neighborhood) AS rn
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


def backtest_footnote(score: dict, report: dict | None) -> str:
    """One line an organizer can read out loud about where a score came from.
    Shared by the block-group and neighborhood detail payloads."""
    if score["model_mode"] == "fallback":
        return "weighted index (fallback) — transparent, sign-checked weights"
    if report:
        bt = report["backtest"]
        return (
            f"model {score['model_version']} · backtest on {report['holdout_year']}: "
            f"Spearman ρ = {bt['spearman']:.2f}, R² = {bt['r2']:.2f}"
        )
    return f"model {score['model_version']}"


def block_detail(con: duckdb.DuckDBPyConnection, geoid: str, report: dict | None) -> dict | None:
    scores = all_scores(con)
    s = scores.get(geoid)
    if s is None:
        return None
    names = block_neighborhoods(con)
    return {
        **s,
        "neighborhood": names.get(geoid),
        "trend": block_trend(con, geoid),
        "backtest_summary": backtest_footnote(s, report),
    }


# ---------------------------------------------------------------------------
# neighborhoods
#
# A neighborhood is not a unit the pipeline scores — scores live on block
# groups. The parcel file's `neighborhood` field gives each block group a
# display name (block_neighborhoods above), and 186 names cover all 625
# scored block groups, so a neighborhood is the set of block groups that
# share a name. Everything below is a deterministic roll-up of those
# members; nothing here is modelled or inferred.
# ---------------------------------------------------------------------------

#: Mirrors vulnerability.DEFAULT_HOT_THRESHOLD. Kept as a literal so the
#: read side doesn't import the gated household module; api.py passes the
#: real one explicitly.
DEFAULT_HOT_THRESHOLD = 70

MAX_AGGREGATE_SIGNALS = 5

#: A direction only wins if this share of the member block groups showing the
#: signal agree on it; otherwise the signal reads "mixed". Without this,
#: Bethune Community's price_yoy (5 members down, 4 up) would be published as
#: "below the city in 9 of 9 block groups", which is not true of any of them.
SIGNAL_DIRECTION_MAJORITY = 2 / 3


def neighborhood_slug(name: str) -> str:
    """URL-safe key for a neighborhood name: lowercase, runs of
    non-alphanumerics collapsed to a single '-'. Needed because real names
    carry '/', "'" and '#' ("Fitzgerald/Marygrove", "Evergreen Lahser 7/8").
    The 186 live names produce 186 unique slugs."""
    return re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")


def neighborhood_members(con: duckdb.DuckDBPyConnection) -> dict[str, list[str]]:
    """{neighborhood name: sorted [bg_geoid, …]} — inverts block_neighborhoods."""
    out: dict[str, list[str]] = {}
    for geoid, name in block_neighborhoods(con).items():
        out.setdefault(name, []).append(geoid)
    for geoids in out.values():
        geoids.sort()
    return out


def slug_index(members: dict[str, list[str]]) -> dict[str, str]:
    """{slug: name}. Reverse resolution is a lookup, not an inverse function.
    On a collision the alphabetically first name wins, so a future re-ingest
    can shift names without producing a 500."""
    index: dict[str, str] = {}
    for name in sorted(members):
        index.setdefault(neighborhood_slug(name), name)
    return index


def _aggregate_signals(geoids: list[str], scores: dict[str, dict]) -> list[dict]:
    """Roll the members' top signals up by feature: how many member block
    groups list it, the mean z, and the direction most of them agree on. Lets
    the UI say "investor buyer share above the city norm in 4 of 5 block
    groups" instead of picking one block group's signals and hiding the rest."""
    agg: dict[str, dict] = {}
    for geoid in geoids:
        score = scores.get(geoid)
        if score is None:
            continue
        for signal in score["top_signals"]:
            row = agg.setdefault(
                signal["feature"],
                {
                    "feature": signal["feature"],
                    "label": signal.get("label", signal["feature"]),
                    "n_members": 0,
                    "_z_sum": 0.0,
                    "_up": 0,
                    "_down": 0,
                },
            )
            row["n_members"] += 1
            row["_z_sum"] += float(signal["z"])
            row["_up" if signal["direction"] == "up" else "_down"] += 1

    n_scored = sum(1 for g in geoids if g in scores)
    out = []
    for row in agg.values():
        n, up, down = row["n_members"], row["_up"], row["_down"]
        if max(up, down) >= n * SIGNAL_DIRECTION_MAJORITY:
            direction = "up" if up > down else "down"
        else:
            direction = "mixed"
        out.append({
            "feature": row["feature"],
            "label": row["label"],
            "n_members": n,
            "n_block_groups": n_scored,
            "n_up": up,
            "n_down": down,
            # NB: an average of cross-sectional z-scores is NOT a z-score for the
            # neighborhood — the city-wide distribution was over block groups.
            # Only ever render this as "in k of n block groups".
            "mean_z": round(row["_z_sum"] / n, 2),
            "direction": direction,
        })
    out.sort(key=lambda r: (-r["n_members"], -abs(r["mean_z"]), r["feature"]))
    return out[:MAX_AGGREGATE_SIGNALS]


def _rollup(
    name: str, geoids: list[str], scores: dict[str, dict], hot_threshold: int
) -> dict | None:
    """One neighborhood's deterministic roll-up. None when no member block
    group has a score."""
    scored = [scores[g] for g in geoids if g in scores]
    if not scored:
        return None
    heats = [s["heat_score"] for s in scored]
    heat_max = max(heats)
    return {
        "name": name,
        "slug": neighborhood_slug(name),
        "n_block_groups": len(scored),
        "n_hot": sum(1 for h in heats if h >= hot_threshold),
        "heat_max": heat_max,
        # half-up, not Python's banker's rounding, so 60.5 reads as 61
        "heat_mean": int(sum(heats) / len(heats) + 0.5),
        # lowest GEOID among ties, so the pick never depends on row order
        "hottest_geoid": min(s["bg_geoid"] for s in scored if s["heat_score"] == heat_max),
        "n_low_confidence": sum(1 for s in scored if s["confidence"] == "low"),
        "top_signals": _aggregate_signals(geoids, scores),
    }


def _rank_key(row: dict) -> tuple:
    """Most at risk first. `heat_max` leads because displacement pressure is
    local — a neighborhood is as exposed as its hottest block group — and the
    UI says so in words. Ties fall to how many block groups are hot, then the
    mean, then the name, so the order is total and stable."""
    return (-row["heat_max"], -row["n_hot"], -row["heat_mean"], row["name"])


def _ranked_rollups(
    members: dict[str, list[str]], scores: dict[str, dict], hot_threshold: int
) -> list[dict]:
    """Every scored neighborhood's roll-up, most at risk first. Pure: takes the
    two lookups already in hand so a caller that needs both one neighborhood and
    its city rank doesn't re-run the parcel join behind `neighborhood_members`."""
    rows = [
        row
        for name, geoids in members.items()
        if (row := _rollup(name, geoids, scores, hot_threshold)) is not None
    ]
    rows.sort(key=_rank_key)
    return rows


def neighborhood_list(
    con: duckdb.DuckDBPyConnection, hot_threshold: int = DEFAULT_HOT_THRESHOLD
) -> list[dict]:
    """Every named neighborhood, ordered most at risk first. Raises
    NotScoredError when `signals train` hasn't run."""
    return _ranked_rollups(neighborhood_members(con), all_scores(con), hot_threshold)


def neighborhood_trend(con: duckdb.DuckDBPyConnection, geoids: list[str]) -> dict:
    """Trend for a set of block groups, shaped exactly like block_trend so the
    frontend's sparklines are reused unchanged.

    Counts are summed from bg_features (already counts, so exact). Medians and
    buyer shares are recomputed from sales_clean over the member block groups
    — the source features.py itself aggregates from — rather than averaging
    block-group medians, which would only ever be an approximation.
    """
    empty = {"years": [], "series": {}, "partial_year": None}
    if not geoids or not _table_exists(con, "bg_features"):
        return empty
    marks = ", ".join("?" * len(geoids))
    has_sales = _table_exists(con, "sales_clean")
    sales_cte = (
        f"""
        SELECT year(sale_date) AS year, count(*) AS n_sales,
               median(ppsf) AS median_ppsf,
               median(amt_sale_price) AS median_price,
               avg(CAST(is_llc_buyer AS INT)) AS llc_share
        FROM sales_clean WHERE bg_geoid IN ({marks}) GROUP BY 1
        """
        if has_sales
        else "SELECT NULL::BIGINT AS year, NULL::BIGINT AS n_sales, NULL::DOUBLE AS median_ppsf, "
        "NULL::DOUBLE AS median_price, NULL::DOUBLE AS llc_share WHERE false"
    )
    # one bind set per IN clause: bg_features always, sales_clean only when present
    params = list(geoids) * (2 if has_sales else 1)
    rows = con.execute(
        f"""
        WITH f AS (
            SELECT year, sum(permit_count) AS permit_count,
                   sum(permit_value) AS permit_value,
                   sum(blight_tickets) AS blight_tickets
            FROM bg_features WHERE bg_geoid IN ({marks}) GROUP BY 1
        ),
        s AS ({sales_cte}),
        years AS (
            SELECT year FROM f UNION SELECT year FROM s WHERE year IS NOT NULL
        )
        SELECT y.year, coalesce(s.n_sales, 0), s.median_ppsf, s.median_price,
               s.llc_share, f.permit_count, f.permit_value, f.blight_tickets
        FROM years y LEFT JOIN f ON f.year = y.year LEFT JOIN s ON s.year = y.year
        ORDER BY y.year
        """,
        params,
    ).fetchall()
    if not rows:
        return empty
    years = [int(r[0]) for r in rows]
    series = {
        col: [None if r[i + 1] is None or r[i + 1] != r[i + 1] else float(r[i + 1]) for r in rows]
        for i, col in enumerate(
            ["n_sales", "median_ppsf", "median_price", "llc_share",
             "permit_count", "permit_value", "blight_tickets"]
        )
    }
    from datetime import date

    partial = date.today().year if years and years[-1] == date.today().year else None
    return {"years": years, "series": series, "partial_year": partial}


def neighborhood_detail(
    con: duckdb.DuckDBPyConnection,
    slug: str,
    report: dict | None,
    hot_threshold: int = DEFAULT_HOT_THRESHOLD,
) -> dict | None:
    """One neighborhood: its roll-up, where it sits among the others, the
    aggregated trend, and its member block groups ranked most at risk first.
    None for an unknown slug."""
    scores = all_scores(con)
    members = neighborhood_members(con)
    name = slug_index(members).get(slug)
    if name is None:
        return None
    geoids = members[name]
    row = _rollup(name, geoids, scores, hot_threshold)
    if row is None:
        return None
    block_groups = sorted(
        (scores[g] for g in geoids if g in scores),
        key=lambda s: (-s["heat_score"], s["bg_geoid"]),
    )
    # city rank from the same order the list page uses, off the lookups already
    # loaded above — this place only means something next to the other 185
    ranked = _ranked_rollups(members, scores, hot_threshold)
    rank = next(i for i, r in enumerate(ranked, 1) if r["name"] == name)
    return {
        **row,
        "rank": rank,
        "n_neighborhoods": len(ranked),
        "heat_min": block_groups[-1]["heat_score"],
        "hot_threshold": hot_threshold,
        "model_mode": block_groups[0]["model_mode"],
        "scored_at": block_groups[0]["scored_at"],
        "backtest_summary": backtest_footnote(block_groups[0], report),
        "trend": neighborhood_trend(con, geoids),
        "block_groups": [
            {
                "bg_geoid": s["bg_geoid"],
                "heat_score": s["heat_score"],
                "confidence": s["confidence"],
                "top_signals": s["top_signals"],
            }
            for s in block_groups
        ],
    }
