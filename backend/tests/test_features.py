"""Unit tests for signals.features: the arm's-length sales filter, YoY math,
corridor-distance geometry, and the full build_features aggregation — all
against tiny synthetic DuckDB fixtures. See md/architecture.md §8.
"""
from __future__ import annotations

import json
from datetime import date

import duckdb
import numpy as np
import pandas as pd
import pytest

from signals import features

# Small squares (~100m) around real Detroit-ish coordinates so UTM 17N
# reprojection in geo.blockgroup_centroids is well-behaved. Centers are
# roughly 0.01 deg (~830m) apart in longitude.
def _square(center_lon: float, center_lat: float, half: float = 0.0005) -> list[list[float]]:
    lo_lon, hi_lon = center_lon - half, center_lon + half
    lo_lat, hi_lat = center_lat - half, center_lat + half
    # clockwise = exterior, per Esri convention (see geo.py)
    return [[lo_lon, lo_lat], [lo_lon, hi_lat], [hi_lon, hi_lat], [hi_lon, lo_lat], [lo_lon, lo_lat]]


BG_CENTERS = {
    "A": (-83.00, 42.33),
    "B": (-82.99, 42.33),   # ~830m east of A
    "C": (-82.98, 42.33),   # ~1660m east of A
    "D": (-83.05, 42.33),   # ~4150m west of A
}


def _base_db() -> duckdb.DuckDBPyConnection:
    con = duckdb.connect(":memory:")
    con.execute("CREATE TABLE raw_blockgroups (GEOID VARCHAR, geometry_json VARCHAR)")
    for geoid, (lon, lat) in BG_CENTERS.items():
        con.execute(
            "INSERT INTO raw_blockgroups VALUES (?, ?)",
            [geoid, json.dumps({"rings": [_square(lon, lat)]})],
        )
    con.execute(
        "CREATE TABLE raw_sales (sale_id INTEGER, parcel_id VARCHAR, sale_date DATE, "
        "amt_sale_price DOUBLE, term_of_sale VARCHAR, grantee VARCHAR)"
    )
    con.execute(
        "CREATE TABLE raw_parcels (parcel_id VARCHAR, total_floor_area DOUBLE, "
        "taxpayer_state VARCHAR, pct_pre_claimed DOUBLE, is_improved INTEGER, "
        "property_class_description VARCHAR)"
    )
    con.execute(
        "CREATE TABLE raw_permits (parcel_id VARCHAR, issued_date DATE, "
        "amt_estimated_contractor_cost DOUBLE, permit_type VARCHAR, work_description VARCHAR)"
    )
    con.execute("CREATE TABLE raw_blight (parcel_id VARCHAR, ticket_issued_date DATE)")
    con.execute("CREATE TABLE parcel_geo (parcel_id VARCHAR, bg_geoid VARCHAR, lon DOUBLE, lat DOUBLE)")
    return con


# ---------------------------------------------------------------------------
# _yoy_log_change
# ---------------------------------------------------------------------------

def test_yoy_log_change_basic():
    df = pd.DataFrame({"bg_geoid": ["A", "A", "A"], "year": [2020, 2021, 2022], "val": [10, 20, 40]})
    out = features._yoy_log_change(df, "val")
    assert np.isnan(out.iloc[0])
    assert out.iloc[1] == pytest.approx(np.log(2))
    assert out.iloc[2] == pytest.approx(np.log(2))


def test_yoy_log_change_min_n_gate_blocks_thin_years():
    df = pd.DataFrame(
        {
            "bg_geoid": ["A", "A", "A"],
            "year": [2020, 2021, 2022],
            "val": [10.0, 20.0, 40.0],
            "n_sales": [5, 1, 5],  # 2021 is too thin
        }
    )
    out = features._yoy_log_change(df, "val", min_n_col="n_sales", min_n=3)
    assert np.isnan(out.iloc[1])  # 2021: prior side fine but current side thin -> NaN
    assert np.isnan(out.iloc[2])  # 2022: prior side (2021) thin -> NaN


def test_yoy_log_change_resets_per_block_group():
    df = pd.DataFrame(
        {"bg_geoid": ["A", "A", "B", "B"], "year": [2020, 2021, 2020, 2021], "val": [10, 10, 5, 20]}
    )
    out = features._yoy_log_change(df, "val")
    assert np.isnan(out.iloc[0])  # A 2020: no prior
    assert out.iloc[1] == pytest.approx(0.0)  # A 2021: no change
    assert np.isnan(out.iloc[2])  # B 2020: no prior (not A's 2021!)
    assert out.iloc[3] == pytest.approx(np.log(4))  # B 2021: 5 -> 20


# ---------------------------------------------------------------------------
# _hot_corridor_distance
# ---------------------------------------------------------------------------

def test_hot_corridor_distance_orders_by_proximity_to_prior_year_hotspot():
    con = _base_db()
    df = pd.DataFrame(
        {
            "bg_geoid": ["A", "B", "C", "D", "A", "B", "C", "D"],
            "year": [2019, 2019, 2019, 2019, 2020, 2020, 2020, 2020],
            "permit_value": [1000.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0],
        }
    )
    dist = features._hot_corridor_distance(con, df)

    d2019 = dist[df["year"] == 2019]
    assert d2019.isna().all()  # no 2018 data -> nothing to compare against

    d2020 = dist[df["year"] == 2020]
    by_bg = dict(zip(df.loc[df["year"] == 2020, "bg_geoid"], d2020))
    assert by_bg["A"] == pytest.approx(0.0, abs=1.0)  # A was itself the only hotspot
    assert by_bg["A"] < by_bg["B"] < by_bg["C"] < by_bg["D"]
    assert by_bg["B"] == pytest.approx(830, rel=0.15)


# ---------------------------------------------------------------------------
# build_features end to end
# ---------------------------------------------------------------------------

def test_build_features_filters_and_aggregates():
    con = _base_db()

    con.execute(
        "INSERT INTO raw_parcels VALUES (?, ?, ?, ?, ?, ?)",
        ["p1", 1000.0, "MI", 100.0, 1, "RESIDENTIAL-IMPROVED"],
    )
    con.execute(
        "INSERT INTO raw_parcels VALUES (?, ?, ?, ?, ?, ?)",
        ["p2", 1000.0, "CA", 0.0, 0, "RESIDENTIAL-VACANT"],
    )
    con.execute(
        "INSERT INTO parcel_geo VALUES (?, ?, ?, ?), (?, ?, ?, ?)",
        ["p1", "A", *BG_CENTERS["A"], "p2", "A", *BG_CENTERS["A"]],
    )

    sales = [
        # sale_id, parcel_id, sale_date, price, term_of_sale, grantee -> kept?
        (1, "p1", date(2020, 6, 1), 100000, "03-ARM'S LENGTH", "SMITH, JANE"),          # keep
        (2, "p1", date(2020, 7, 1), 120000, "19-MULTI PARCEL ARM'S LENGTH", "DOE LLC"),  # keep, LLC
        (3, "p2", date(2020, 8, 1), 5000, "13-GOVERNMENT", "CITY OF DETROIT"),           # drop: not arm's length
        (4, "p2", date(2020, 9, 1), 500, "03-ARM'S LENGTH", "CHEAP BUYER"),              # drop: below price floor
        (5, "p2", date(2925, 1, 1), 90000, "03-ARM'S LENGTH", "TYPO YEAR"),              # drop: bad date
    ]
    for row in sales:
        con.execute("INSERT INTO raw_sales VALUES (?, ?, ?, ?, ?, ?)", list(row))

    con.execute(
        "INSERT INTO raw_permits VALUES (?, ?, ?, ?, ?)",
        ["p1", date(2020, 3, 1), 50000.0, "BLDG-RESIDENTIAL", "new construction of garage"],
    )
    con.execute(
        "INSERT INTO raw_blight VALUES (?, ?)",
        ["p2", date(2020, 5, 1)],
    )

    df = features.build_features(con)

    assert set(df.columns) == {
        "bg_geoid", "year", "n_sales", "median_price", "median_ppsf", "price_yoy",
        "llc_share", "out_of_state_share", "permit_count", "permit_value",
        "new_construction_permits", "permit_count_yoy", "blight_tickets",
        "vacant_share", "owner_occ_share", "dist_to_hot_corridor_m",
    }

    row_2020 = df[(df["bg_geoid"] == "A") & (df["year"] == 2020)].iloc[0]
    assert row_2020["n_sales"] == 2  # only the two arm's-length, price>1000, valid-date sales
    assert row_2020["median_price"] == pytest.approx(110000)
    assert row_2020["llc_share"] == pytest.approx(0.5)
    assert row_2020["permit_count"] == 1
    assert row_2020["permit_value"] == pytest.approx(50000)
    assert row_2020["new_construction_permits"] == 1
    assert row_2020["blight_tickets"] == 1
    assert row_2020["vacant_share"] == pytest.approx(0.5)  # p1 improved, p2 vacant
    assert row_2020["owner_occ_share"] == pytest.approx(0.5)  # only p1 has pct_pre_claimed > 0

    # sales_clean was also written and excludes the 3 dropped rows
    n_clean = con.execute("SELECT count(*) FROM sales_clean").fetchone()[0]
    assert n_clean == 2

    # every (bg_geoid, year) combination is present, not just years with data
    years_for_a = set(df.loc[df["bg_geoid"] == "A", "year"])
    assert features.FIRST_SALES_YEAR in years_for_a
    assert 2020 in years_for_a
