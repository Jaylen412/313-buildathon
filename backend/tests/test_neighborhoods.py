"""Neighborhood roll-up and routes over an in-memory DuckDB.

The fixture is shaped to catch the cases that actually bite: a neighborhood
spanning two block groups, a name containing '/', a block group with no parcels
(so no name), and per-block-group sale prices chosen so a pooled median differs
from the average of the block-group medians.
"""
from __future__ import annotations

import json
from datetime import date, datetime, timezone

import duckdb
import pytest
from fastapi.testclient import TestClient

from signals import api, store
from signals.config import Settings

NOW = datetime(2026, 9, 18, tzinfo=timezone.utc)
THIS_YEAR = date.today().year


def _signals(*specs: tuple[str, float, str]) -> str:
    return json.dumps(
        [
            {"feature": f, "value": 0.5, "z": z, "direction": d, "weight": 0.01}
            for f, z, d in specs
        ]
    )


def _con() -> duckdb.DuckDBPyConnection:
    con = duckdb.connect(":memory:")
    con.execute(
        "CREATE TABLE bg_scores (bg_geoid VARCHAR, heat_score INTEGER, predicted_growth DOUBLE, "
        "confidence VARCHAR, top_signals JSON, model_version VARCHAR, model_mode VARCHAR, scored_at TIMESTAMPTZ)"
    )
    rows = [
        # Fitzgerald/Marygrove: two block groups, both hot, one low-confidence.
        # llc_share agrees (both up); price_yoy disagrees (one up, one down).
        ("A", 98, "ok", _signals(("llc_share", 1.9, "up"), ("price_yoy", -0.8, "down"))),
        ("B", 72, "low", _signals(("llc_share", 1.1, "up"), ("price_yoy", 0.6, "up"))),
        # Claytown: one cool block group.
        ("C", 30, "ok", _signals(("n_sales", -0.4, "down"))),
        # D has no parcel rows, so no neighborhood name: must be skipped.
        ("D", 55, "ok", "[]"),
    ]
    for geoid, heat, conf, sигs in rows:
        con.execute(
            "INSERT INTO bg_scores VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            [geoid, heat, 0.3, conf, sигs, "hgb-v1", "trained", NOW],
        )
    con.execute(
        "CREATE TABLE bg_features (bg_geoid VARCHAR, year INTEGER, n_sales INTEGER, median_ppsf DOUBLE, "
        "median_price DOUBLE, llc_share DOUBLE, permit_count INTEGER, permit_value DOUBLE, blight_tickets INTEGER)"
    )
    # A and B each have permits/blight in 2024, 2025 and the partial current year.
    for geoid, permits in [("A", 3), ("B", 7), ("C", 1)]:
        for year in (2024, 2025, THIS_YEAR):
            con.execute(
                "INSERT INTO bg_features VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                [geoid, year, 2, 40.0, 60000.0, 0.5, permits, 1e5, 11],
            )
    con.execute(
        "CREATE TABLE sales_clean (sale_id BIGINT, parcel_id VARCHAR, sale_date DATE, "
        "amt_sale_price BIGINT, ppsf DOUBLE, is_llc_buyer BOOLEAN, is_out_of_state_buyer BOOLEAN, bg_geoid VARCHAR)"
    )
    # 2025 prices: A = [10, 20, 30] (median 20), B = [100] (median 100).
    # Average of the two block-group medians would be 60; the pooled median of
    # [10, 20, 30, 100] is 25. The aggregate must be 25.
    sales = [(10, "A", True), (20, "A", False), (30, "A", False), (100, "B", True)]
    for i, (price, geoid, llc) in enumerate(sales):
        con.execute(
            "INSERT INTO sales_clean VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            [i, f"p{i}", date(2025, 6, 1), price, float(price), llc, False, geoid],
        )
    con.execute("CREATE TABLE parcel_geo (parcel_id VARCHAR, bg_geoid VARCHAR, lon DOUBLE, lat DOUBLE)")
    con.execute("CREATE TABLE raw_parcels (parcel_id VARCHAR, neighborhood VARCHAR)")
    parcels = [("a1", "A", "Fitzgerald/Marygrove"), ("b1", "B", "Fitzgerald/Marygrove"), ("c1", "C", "Claytown")]
    for pid, geoid, name in parcels:
        con.execute("INSERT INTO parcel_geo VALUES (?, ?, 0, 0)", [pid, geoid])
        con.execute("INSERT INTO raw_parcels VALUES (?, ?)", [pid, name])
    return con


@pytest.fixture
def con():
    return _con()


@pytest.fixture
def client(tmp_path, monkeypatch):
    settings = Settings(_env_file=None, DATA_DIR=str(tmp_path), SIGNALS_ORG_TOKEN="secret")
    monkeypatch.setattr(api, "get_settings", lambda: settings)
    monkeypatch.setattr(api, "get_con", _con)
    monkeypatch.setattr(api, "load_report", lambda: {"holdout_year": 2023, "backtest": {"spearman": 0.386, "r2": 0.105}})
    api._neighborhoods_cache.update(stamp=None, payload=None)
    return TestClient(api.app)


# --------------------------------------------------------------------------- slugs

@pytest.mark.parametrize(
    "name, slug",
    [
        ("Fitzgerald/Marygrove", "fitzgerald-marygrove"),
        ("O'Hair Park", "o-hair-park"),
        ("Grandmont #1", "grandmont-1"),
        ("Evergreen Lahser 7/8", "evergreen-lahser-7-8"),
        ("Barton-McFarland", "barton-mcfarland"),
    ],
)
def test_slugify(name, slug):
    assert store.neighborhood_slug(name) == slug


def test_slug_collisions_resolve_to_the_alphabetically_first_name():
    # "A/B" and "A-B" both slug to "a-b"; the first name alphabetically wins,
    # deterministically, so a re-ingest can never 500 on a collision.
    index = store.slug_index({"A/B": ["x"], "A-B": ["y"]})
    assert index["a-b"] == "A-B"


def test_members_invert_the_name_map(con):
    members = store.neighborhood_members(con)
    assert members["Fitzgerald/Marygrove"] == ["A", "B"]
    assert members["Claytown"] == ["C"]
    assert "D" not in [g for gs in members.values() for g in gs]


# --------------------------------------------------------------------------- roll-up

def test_rollup_counts_and_ordering(con):
    rows = store.neighborhood_list(con, hot_threshold=70)
    assert [r["name"] for r in rows] == ["Fitzgerald/Marygrove", "Claytown"]
    top = rows[0]
    assert top["slug"] == "fitzgerald-marygrove"
    assert top["n_block_groups"] == 2
    assert top["n_hot"] == 2  # 98 and 72 both clear the threshold
    assert top["n_low_confidence"] == 1
    assert top["heat_max"] == 98
    assert top["heat_mean"] == 85  # (98 + 72) / 2
    assert top["hottest_geoid"] == "A"


def test_hot_count_respects_the_threshold(con):
    rows = {r["name"]: r for r in store.neighborhood_list(con, hot_threshold=90)}
    assert rows["Fitzgerald/Marygrove"]["n_hot"] == 1  # only the 98
    assert rows["Claytown"]["n_hot"] == 0


def test_unnamed_block_group_is_excluded(con):
    rows = store.neighborhood_list(con)
    counted = sum(r["n_block_groups"] for r in rows)
    assert counted == 3  # A, B, C — D has no name


def test_signals_that_disagree_read_as_mixed(con):
    rows = store.neighborhood_list(con, hot_threshold=70)
    by_feature = {s["feature"]: s for s in rows[0]["top_signals"]}
    # both block groups are above the city on llc_share
    assert by_feature["llc_share"]["direction"] == "up"
    assert by_feature["llc_share"]["n_members"] == 2
    # ...but they disagree on price_yoy, so it must not claim a side
    assert by_feature["price_yoy"]["direction"] == "mixed"
    assert (by_feature["price_yoy"]["n_up"], by_feature["price_yoy"]["n_down"]) == (1, 1)


# --------------------------------------------------------------------------- trend

def test_trend_pools_sales_rather_than_averaging_block_medians(con):
    trend = store.neighborhood_trend(con, ["A", "B"])
    i = trend["years"].index(2025)
    # pooled median of [10, 20, 30, 100] is 25, not the 60 an average of the
    # per-block-group medians (20 and 100) would give
    assert trend["series"]["median_price"][i] == 25.0
    assert trend["series"]["median_ppsf"][i] == 25.0
    assert trend["series"]["n_sales"][i] == 4
    assert trend["series"]["llc_share"][i] == pytest.approx(0.5)


def test_trend_sums_counts_across_members(con):
    trend = store.neighborhood_trend(con, ["A", "B"])
    i = trend["years"].index(2025)
    assert trend["series"]["permit_count"][i] == 10  # 3 + 7
    assert trend["series"]["blight_tickets"][i] == 22  # 11 + 11


def test_trend_flags_the_partial_current_year(con):
    trend = store.neighborhood_trend(con, ["A", "B"])
    assert trend["partial_year"] == THIS_YEAR
    assert trend["years"][-1] == THIS_YEAR
    # no sales rows in the current year, so medians are null but the year exists
    assert trend["series"]["median_ppsf"][-1] is None
    assert trend["series"]["n_sales"][-1] == 0


def test_trend_without_sales_clean_still_returns_permit_series():
    con = _con()
    con.execute("DROP TABLE sales_clean")
    trend = store.neighborhood_trend(con, ["A", "B"])
    assert trend["years"], "years should still come from bg_features"
    assert all(v is None for v in trend["series"]["median_ppsf"])
    assert trend["series"]["permit_count"][0] == 10


def test_trend_of_no_members_is_empty(con):
    assert store.neighborhood_trend(con, []) == {"years": [], "series": {}, "partial_year": None}


# --------------------------------------------------------------------------- detail

def test_detail_ranks_members_and_carries_the_footnote(con):
    detail = store.neighborhood_detail(con, "fitzgerald-marygrove", {"model_version": "hgb-v1", "holdout_year": 2023, "backtest": {"spearman": 0.386, "r2": 0.105}})
    assert detail["name"] == "Fitzgerald/Marygrove"
    assert [m["bg_geoid"] for m in detail["block_groups"]] == ["A", "B"]
    assert detail["block_groups"][0]["heat_score"] == 98
    assert "Spearman" in detail["backtest_summary"]
    assert detail["trend"]["years"]


def test_detail_unknown_slug_is_none(con):
    assert store.neighborhood_detail(con, "not-a-place", None) is None


# --------------------------------------------------------------------------- routes

def test_list_route_shape_and_order(client):
    body = client.get("/api/neighborhoods").json()
    assert body["hot_threshold"] == 70
    assert [n["name"] for n in body["neighborhoods"]] == ["Fitzgerald/Marygrove", "Claytown"]
    assert set(body["neighborhoods"][0]) == {
        "name", "slug", "n_block_groups", "n_hot", "heat_max", "heat_mean",
        "hottest_geoid", "n_low_confidence", "top_signals",
    }


def test_public_routes_leak_no_parcel_or_household_data(client):
    for path in ("/api/neighborhoods", "/api/neighborhoods/fitzgerald-marygrove"):
        body = json.dumps(client.get(path).json())
        assert "parcel_id" not in body
        assert "households" not in body
        assert "taxpayer" not in body


def test_detail_route_resolves_a_name_containing_a_slash(client):
    response = client.get("/api/neighborhoods/fitzgerald-marygrove")
    assert response.status_code == 200
    assert response.json()["name"] == "Fitzgerald/Marygrove"


def test_detail_route_unknown_slug_is_404(client):
    assert client.get("/api/neighborhoods/nowhere").status_code == 404


def test_summary_route_requires_the_org_token(client):
    assert client.post("/api/neighborhoods/claytown/summary").status_code == 403
    assert client.post(
        "/api/neighborhoods/claytown/summary", headers={"X-Org-Token": "wrong"}
    ).status_code == 403


def test_summary_route_returns_the_explainer(client, monkeypatch):
    from signals.explain import MetricExplainer

    explainer = MetricExplainer(
        summary="Claytown is heating up: sales rose and investors took a bigger share.",
    )

    def fake(con, slug, report, settings=None, client=None, force=False, hot_threshold=70):
        summary = type("S", (), {"name": "Claytown"})()
        return explainer, True, summary

    monkeypatch.setattr(api.explain, "get_or_create_explainer", fake)
    body = client.post("/api/neighborhoods/claytown/summary", headers={"X-Org-Token": "secret"}).json()
    assert body["name"] == "Claytown"
    assert body["cached"] is True
    # the paragraph is returned as a plain string, not a one-key object
    assert body["summary"].startswith("Claytown is heating up")


def test_summary_route_unknown_slug_is_404(client, monkeypatch):
    monkeypatch.setattr(api.explain, "get_or_create_explainer", lambda *a, **k: None)
    response = client.post("/api/neighborhoods/nowhere/summary", headers={"X-Org-Token": "secret"})
    assert response.status_code == 404


def test_summary_route_maps_a_missing_key_to_503(client, monkeypatch):
    def boom(*args, **kwargs):
        raise RuntimeError("OPENAI_API_KEY is not set (backend/.env)")

    monkeypatch.setattr(api.explain, "get_or_create_explainer", boom)
    response = client.post("/api/neighborhoods/claytown/summary", headers={"X-Org-Token": "secret"})
    assert response.status_code == 503
    assert "OPENAI_API_KEY" in response.json()["detail"]


def test_summary_route_maps_a_provider_error_to_502(client, monkeypatch):
    def boom(*args, **kwargs):
        raise ValueError("connection reset")

    monkeypatch.setattr(api.explain, "get_or_create_explainer", boom)
    response = client.post("/api/neighborhoods/claytown/summary", headers={"X-Org-Token": "secret"})
    assert response.status_code == 502
    assert "summary generation failed" in response.json()["detail"]
