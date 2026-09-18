"""API tests: public block routes over an in-memory DuckDB with synthetic
scores, plus the org-token gate. api.get_con / api.get_settings are
monkeypatched so no file database or real .env is touched.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone

import duckdb
import pytest
from fastapi.testclient import TestClient

from signals import api
from signals.config import Settings


def _con() -> duckdb.DuckDBPyConnection:
    con = duckdb.connect(":memory:")
    con.execute(
        "CREATE TABLE bg_scores (bg_geoid VARCHAR, heat_score INTEGER, predicted_growth DOUBLE, "
        "confidence VARCHAR, top_signals JSON, model_version VARCHAR, model_mode VARCHAR, scored_at TIMESTAMPTZ)"
    )
    now = datetime(2026, 9, 18, tzinfo=timezone.utc)  # tz-aware, like the real scored_at (needs pytz)
    sig = json.dumps([{"feature": "llc_share", "value": 0.8, "z": 1.9, "direction": "up", "weight": 0.01}])
    con.execute("INSERT INTO bg_scores VALUES (?, ?, ?, ?, ?, ?, ?, ?)", ["A", 95, 0.4, "ok", sig, "hgb-v1", "trained", now])
    con.execute("INSERT INTO bg_scores VALUES (?, ?, ?, ?, ?, ?, ?, ?)", ["B", 10, -0.1, "low", "[]", "hgb-v1", "trained", now])
    con.execute(
        "CREATE TABLE bg_features (bg_geoid VARCHAR, year INTEGER, n_sales INTEGER, median_ppsf DOUBLE, "
        "median_price DOUBLE, llc_share DOUBLE, permit_count INTEGER, permit_value DOUBLE, blight_tickets INTEGER)"
    )
    for year, ppsf in [(2023, 40.0), (2024, 55.0), (2025, 70.0), (2026, None)]:
        con.execute("INSERT INTO bg_features VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)", ["A", year, 5, ppsf, 60000, 0.5, 3, 1e5, 7])
    con.execute("CREATE TABLE parcel_geo (parcel_id VARCHAR, bg_geoid VARCHAR, lon DOUBLE, lat DOUBLE)")
    con.execute("CREATE TABLE raw_parcels (parcel_id VARCHAR, neighborhood VARCHAR)")
    for i in range(3):
        con.execute("INSERT INTO parcel_geo VALUES (?, 'A', 0, 0)", [f"p{i}"])
        con.execute("INSERT INTO raw_parcels VALUES (?, ?)", [f"p{i}", "Corktown" if i < 2 else "Hubbard Richard"])
    return con


@pytest.fixture
def client(tmp_path, monkeypatch):
    settings = Settings(_env_file=None, DATA_DIR=str(tmp_path), SIGNALS_ORG_TOKEN="secret")
    geojson = {
        "type": "FeatureCollection",
        "features": [
            {"type": "Feature", "geometry": {"type": "Polygon", "coordinates": [[[0, 0], [0, 1], [1, 1], [0, 0]]]}, "properties": {"bg_geoid": "A"}},
            {"type": "Feature", "geometry": {"type": "Polygon", "coordinates": [[[1, 0], [1, 1], [2, 1], [1, 0]]]}, "properties": {"bg_geoid": "B"}},
        ],
    }
    (tmp_path / "blockgroups.geojson").write_text(json.dumps(geojson))
    monkeypatch.setattr(api, "get_settings", lambda: settings)
    monkeypatch.setattr(api, "get_con", _con)
    monkeypatch.setattr(api, "load_report", lambda: {"holdout_year": 2023, "backtest": {"spearman": 0.386, "r2": 0.105}})
    api._blocks_cache.update(stamp=None, payload=None)
    return TestClient(api.app)


def test_blocks_feature_collection_joins_scores_and_names(client):
    resp = client.get("/api/blocks")
    assert resp.status_code == 200
    body = resp.json()
    assert body["type"] == "FeatureCollection"
    props = {f["properties"]["bg_geoid"]: f["properties"] for f in body["features"]}
    assert props["A"]["heat_score"] == 95
    assert props["A"]["neighborhood"] == "Corktown"  # majority of parcels
    assert props["A"]["top_signals"][0]["label"].startswith("share of sales bought by LLCs")
    assert props["B"]["confidence"] == "low"
    assert props["B"]["neighborhood"] is None  # no parcels in B
    # never leaks parcel-level fields
    assert set(props["A"]) == {"bg_geoid", "neighborhood", "heat_score", "confidence", "top_signals", "model_mode"}


def test_blocks_payload_is_cached_until_scores_change(client, monkeypatch):
    first = client.get("/api/blocks").json()
    assert api._blocks_cache["payload"] is first or api._blocks_cache["payload"] == first
    stamp = api._blocks_cache["stamp"]
    client.get("/api/blocks")
    assert api._blocks_cache["stamp"] == stamp


def test_block_detail_has_trend_and_footnote(client):
    resp = client.get("/api/blocks/A")
    assert resp.status_code == 200
    body = resp.json()
    assert body["heat_score"] == 95
    assert body["neighborhood"] == "Corktown"
    assert body["trend"]["years"] == [2023, 2024, 2025, 2026]
    assert body["trend"]["series"]["median_ppsf"] == [40.0, 55.0, 70.0, None]
    assert body["trend"]["partial_year"] == 2026
    assert "Spearman ρ = 0.39" in body["backtest_summary"]


def test_unknown_block_is_404(client):
    assert client.get("/api/blocks/nope").status_code == 404


def test_health_reports_scoring_state(client):
    body = client.get("/api/health").json()
    assert body["ok"] is True
    # settings.db_path doesn't exist in the tmp dir, so health reports "not scored"
    assert body["n_scored"] == 0


def test_gated_routes_require_token(client):
    assert client.get("/api/blocks/A/households").status_code == 403
    assert client.get("/api/blocks/A/households", headers={"X-Org-Token": "wrong"}).status_code == 403
    assert client.post("/api/blocks/A/brief", headers={"X-Org-Token": "secret"}).status_code == 501


def _fake_households(con, geoid, hot_threshold=70, persist=True, today=None):
    from signals.vulnerability import Household

    return [
        Household(parcel_id="p1", bg_geoid=geoid, rank=1, score=8.4, reasons=["Owned 21+ years"], heirship_flag=False,
                  address="1234 VINEWOOD ST", owner="SMITH, JOHN", tenure_years=21.5, has_pre=False,
                  unpaid_blight_balance=500.0, uncapping_gap=0.62)
    ]


def test_households_are_anonymized_in_demo_mode(client, monkeypatch, tmp_path):
    monkeypatch.setattr(api.vulnerability, "rank", _fake_households)
    monkeypatch.setattr(api.vulnerability, "is_hot", lambda con, g, t: True)
    monkeypatch.setattr(api, "get_settings", lambda: Settings(_env_file=None, DATA_DIR=str(tmp_path), SIGNALS_ORG_TOKEN="secret", SIGNALS_DEMO=True))
    body = client.get("/api/blocks/A/households", headers={"X-Org-Token": "secret"}).json()
    assert body["hot"] is True and body["anonymized"] is True
    h = body["households"][0]
    assert h["address"] == "1200 block of VINEWOOD ST"
    assert "parcel_id" not in h and "owner" not in h
    assert h["reasons"] == ["Owned 21+ years"]


def test_households_full_detail_outside_demo_mode(client, monkeypatch, tmp_path):
    monkeypatch.setattr(api.vulnerability, "rank", _fake_households)
    monkeypatch.setattr(api.vulnerability, "is_hot", lambda con, g, t: True)
    monkeypatch.setattr(api, "get_settings", lambda: Settings(_env_file=None, DATA_DIR=str(tmp_path), SIGNALS_ORG_TOKEN="secret", SIGNALS_DEMO=False))
    h = client.get("/api/blocks/A/households", headers={"X-Org-Token": "secret"}).json()["households"][0]
    assert h["address"] == "1234 VINEWOOD ST" and h["parcel_id"] == "p1" and h["owner"] == "SMITH, JOHN"


def test_households_cold_block_group_returns_hot_false(client, monkeypatch):
    monkeypatch.setattr(api.vulnerability, "is_hot", lambda con, g, t: False)
    body = client.get("/api/blocks/B/households", headers={"X-Org-Token": "secret"}).json()
    assert body["hot"] is False and body["households"] == []
    assert client.get("/api/blocks/nope/households", headers={"X-Org-Token": "secret"}).status_code == 404
