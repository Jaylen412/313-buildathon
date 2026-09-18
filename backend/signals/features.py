"""Block-group x year feature aggregation.

Contract (md/architecture.md §5-6):
    build_features(con) -> pd.DataFrame   # writes sales_clean + bg_features

The arm's-length filter is grounded in the real `term_of_sale` value set
(queried live 2026-09-18): the assessor uses a controlled vocabulary where
exactly two of ~15 categories are genuinely arm's-length —
"03-ARM'S LENGTH" (100,712 of 537,595 rows) and "19-MULTI PARCEL ARM'S
LENGTH" (12,116 rows). Everything else (government, foreclosure,
family/related-entity, lending-institution, life estate, "not used/other",
etc.) is excluded. Matching on the literal "ARM'S LENGTH" substring catches
both without hardcoding the numeric prefix, which the assessor could
renumber.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

import duckdb

from signals import geo

MIN_ARMS_LENGTH_PRICE = 1000
FIRST_SALES_YEAR = 2011
MIN_FLOOR_AREA_SQFT = 200
TOP_HOT_CORRIDORS_N = 25
MIN_SALES_FOR_YOY = 3

# See md/architecture.md §5. DuckDB regex is RE2; \b word boundaries work.
LLC_BUYER_PATTERN = r"\b(LLC|L\.L\.C|INC|CORP|TRUST|HOLDINGS|PROPERTIES|INVEST\w*|VENTURES|GROUP)\b"

SALES_CLEAN_SQL = f"""
CREATE OR REPLACE TABLE sales_clean AS
SELECT
    s.sale_id,
    s.parcel_id,
    s.sale_date,
    s.amt_sale_price,
    CASE WHEN p.total_floor_area > {MIN_FLOOR_AREA_SQFT}
         THEN s.amt_sale_price / p.total_floor_area END AS ppsf,
    COALESCE(regexp_matches(upper(COALESCE(s.grantee, '')), '{LLC_BUYER_PATTERN}'), false) AS is_llc_buyer,
    (p.taxpayer_state IS NOT NULL AND p.taxpayer_state != 'MI') AS is_out_of_state_buyer,
    g.bg_geoid
FROM raw_sales s
LEFT JOIN raw_parcels p ON p.parcel_id = s.parcel_id
LEFT JOIN parcel_geo g ON g.parcel_id = s.parcel_id
WHERE upper(s.term_of_sale) LIKE '%ARM''S LENGTH%'
  AND s.amt_sale_price > {MIN_ARMS_LENGTH_PRICE}
  AND s.sale_date >= DATE '{FIRST_SALES_YEAR}-01-01'
  AND s.sale_date <= current_date
"""

SALES_AGG_SQL = """
SELECT
    bg_geoid,
    year(sale_date) AS year,
    count(*) AS n_sales,
    median(amt_sale_price) AS median_price,
    median(ppsf) AS median_ppsf,
    avg(CASE WHEN is_llc_buyer THEN 1.0 ELSE 0.0 END) AS llc_share,
    avg(CASE WHEN is_out_of_state_buyer THEN 1.0 ELSE 0.0 END) AS out_of_state_share
FROM sales_clean
WHERE bg_geoid IS NOT NULL
GROUP BY bg_geoid, year(sale_date)
"""

PERMITS_AGG_SQL = f"""
SELECT
    g.bg_geoid,
    year(pr.issued_date) AS year,
    count(*) AS permit_count,
    sum(COALESCE(pr.amt_estimated_contractor_cost, 0)) AS permit_value,
    sum(CASE WHEN pr.permit_type ILIKE '%new%' OR pr.work_description ILIKE '%new construction%'
             THEN 1 ELSE 0 END) AS new_construction_permits
FROM raw_permits pr
JOIN parcel_geo g ON g.parcel_id = pr.parcel_id
WHERE g.bg_geoid IS NOT NULL
  AND year(pr.issued_date) BETWEEN {FIRST_SALES_YEAR} AND year(current_date)
GROUP BY g.bg_geoid, year(pr.issued_date)
"""

BLIGHT_AGG_SQL = f"""
SELECT
    g.bg_geoid,
    year(b.ticket_issued_date) AS year,
    count(*) AS blight_tickets
FROM raw_blight b
JOIN parcel_geo g ON g.parcel_id = b.parcel_id
WHERE g.bg_geoid IS NOT NULL
  AND year(b.ticket_issued_date) BETWEEN {FIRST_SALES_YEAR} AND year(current_date)
GROUP BY g.bg_geoid, year(b.ticket_issued_date)
"""

# Permits and blight carry junk dates too (blight: 56 rows in years 2027-8535,
# 8 rows before 2000, measured on the real pull) — bound both aggregates to
# [FIRST_SALES_YEAR, current year] so a typo can't stretch the year grid.

# vacant_share / owner_occ_share are current-snapshot, not per-year (the
# parcel file only carries "now", not history) — see md/architecture.md §5.
SNAPSHOT_AGG_SQL = """
SELECT
    g.bg_geoid,
    avg(CASE WHEN p.is_improved = 0 OR p.property_class_description ILIKE '%vacant%'
             THEN 1.0 ELSE 0.0 END) AS vacant_share,
    avg(CASE WHEN p.pct_pre_claimed > 0 THEN 1.0 ELSE 0.0 END) AS owner_occ_share
FROM raw_parcels p
JOIN parcel_geo g ON g.parcel_id = p.parcel_id
WHERE g.bg_geoid IS NOT NULL
GROUP BY g.bg_geoid
"""

ALL_BLOCK_GROUPS_SQL = "SELECT DISTINCT bg_geoid FROM parcel_geo WHERE bg_geoid IS NOT NULL"

COUNT_FILL_ZERO_COLUMNS = [
    "n_sales", "permit_count", "permit_value", "new_construction_permits", "blight_tickets",
]

# The permits layer starts 2019-01-02 (md/architecture.md §1). Before that,
# "0 permits" would mean "no data", not "no activity" — keep it NaN so the
# forecast (which handles NaN natively) can't learn a fake pre-2019 lull.
PERMIT_DATA_START_YEAR = 2019
PERMIT_COLUMNS = ["permit_count", "permit_value", "new_construction_permits"]


def _yoy_log_change(
    df: pd.DataFrame, col: str, min_n_col: str | None = None, min_n: int = 0
) -> pd.Series:
    """log(current / prior year) within each bg_geoid, assuming df is sorted
    by (bg_geoid, year) with a complete year grid (so shift(1) is the prior
    year, not just the prior row). NaN when either side is zero/missing, or
    (if min_n_col is given) when either side's row count is below min_n."""
    grouped = df.groupby("bg_geoid", sort=False)
    current = df[col]
    prior = grouped[col].shift(1)
    with np.errstate(divide="ignore", invalid="ignore"):
        change = np.log(current.replace(0, np.nan)) - np.log(prior.replace(0, np.nan))
    if min_n_col is not None:
        prior_n = grouped[min_n_col].shift(1)
        change = change.where((df[min_n_col] >= min_n) & (prior_n >= min_n))
    return change


def _hot_corridor_distance(con: duckdb.DuckDBPyConnection, df: pd.DataFrame) -> pd.Series:
    """Distance (meters) from each row's block-group centroid to the nearest
    of the top-N block groups by permit_value in the *prior* year. NaN for
    years with no prior-year permit data (i.e. before 2020, since permits
    start in 2019 — see md/architecture.md §1)."""
    centroids = geo.blockgroup_centroids(con).set_index("bg_geoid")
    xy = pd.DataFrame(
        {"x": centroids.geometry.x, "y": centroids.geometry.y}, index=centroids.index
    )

    result = pd.Series(np.nan, index=df.index, dtype=float)
    for year, group in df.groupby("year"):
        prior = df.loc[df["year"] == year - 1]
        hot = prior.nlargest(TOP_HOT_CORRIDORS_N, "permit_value")
        hot = hot.loc[hot["permit_value"] > 0]
        if hot.empty:
            continue
        hot_xy = xy.reindex(hot["bg_geoid"]).dropna().to_numpy()
        if len(hot_xy) == 0:
            continue
        rows_xy = xy.reindex(group["bg_geoid"]).to_numpy()
        valid = ~np.isnan(rows_xy).any(axis=1)
        diff = rows_xy[valid, None, :] - hot_xy[None, :, :]
        dist = np.sqrt((diff**2).sum(axis=2)).min(axis=1)
        result.loc[group.index[valid]] = dist
    return result


def build_features(con: duckdb.DuckDBPyConnection) -> pd.DataFrame:
    """Filter raw_sales to arm's-length sales (sales_clean), then aggregate
    parcel_geo + sales_clean + raw_permits + raw_blight to bg_features (one
    row per bg_geoid x year, FIRST_SALES_YEAR-current). See §5 for columns."""
    con.execute(SALES_CLEAN_SQL)

    sales_agg = con.execute(SALES_AGG_SQL).fetchdf()
    permits_agg = con.execute(PERMITS_AGG_SQL).fetchdf()
    blight_agg = con.execute(BLIGHT_AGG_SQL).fetchdf()
    snapshot_agg = con.execute(SNAPSHOT_AGG_SQL).fetchdf()
    all_bg = con.execute(ALL_BLOCK_GROUPS_SQL).fetchdf()["bg_geoid"]

    # Fixed grid: never let the data extend it (junk future dates exist).
    years = range(FIRST_SALES_YEAR, pd.Timestamp.now().year + 1)

    grid = pd.MultiIndex.from_product([all_bg, years], names=["bg_geoid", "year"]).to_frame(
        index=False
    )
    df = grid.merge(sales_agg, on=["bg_geoid", "year"], how="left")
    df = df.merge(permits_agg, on=["bg_geoid", "year"], how="left")
    df = df.merge(blight_agg, on=["bg_geoid", "year"], how="left")
    df = df.merge(snapshot_agg, on="bg_geoid", how="left")

    for col in COUNT_FILL_ZERO_COLUMNS:
        df[col] = df[col].fillna(0)
    df.loc[df["year"] < PERMIT_DATA_START_YEAR, PERMIT_COLUMNS] = np.nan

    df = df.sort_values(["bg_geoid", "year"]).reset_index(drop=True)
    df["price_yoy"] = _yoy_log_change(df, "median_ppsf", min_n_col="n_sales", min_n=MIN_SALES_FOR_YOY)
    df["permit_count_yoy"] = _yoy_log_change(df, "permit_count")
    df["dist_to_hot_corridor_m"] = _hot_corridor_distance(con, df)

    column_order = [
        "bg_geoid", "year", "n_sales", "median_price", "median_ppsf", "price_yoy",
        "llc_share", "out_of_state_share", "permit_count", "permit_value",
        "new_construction_permits", "permit_count_yoy", "blight_tickets",
        "vacant_share", "owner_occ_share", "dist_to_hot_corridor_m",
    ]
    df = df[column_order]

    con.register("_bg_features_tmp", df)
    try:
        con.execute("CREATE OR REPLACE TABLE bg_features AS SELECT * FROM _bg_features_tmp")
    finally:
        con.unregister("_bg_features_tmp")

    print(f"bg_features: {len(df)} rows ({df['bg_geoid'].nunique()} block groups x {len(years)} years)")
    return df
