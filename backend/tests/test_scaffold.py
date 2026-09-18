"""Scaffold smoke tests: every module imports and the app + settings boot.

Real unit tests land alongside each module in later build-order steps (see
md/architecture.md §8: paginator, sales filters, feature aggregation,
fallback determinism, vulnerability reasons, brief schema).
"""
from fastapi.testclient import TestClient

from signals import brief, config, db, demo, features, forecast, geo, ingest, sources, vulnerability
from signals.api import app


def test_modules_import() -> None:
    assert all([brief, config, db, demo, features, forecast, geo, ingest, sources, vulnerability])


def test_settings_load() -> None:
    settings = config.get_settings()
    assert settings.geo_level == config.GeoLevel.BLOCK_GROUP


def test_sources_layers_have_query_urls() -> None:
    for layer in sources.ALL_LAYERS:
        assert layer.query_url.startswith("https://services2.arcgis.com/")
        assert layer.out_fields


def test_health_endpoint() -> None:
    client = TestClient(app)
    resp = client.get("/api/health")
    assert resp.status_code == 200
    assert resp.json()["ok"] is True


def test_household_route_requires_org_token() -> None:
    client = TestClient(app)
    resp = client.get("/api/blocks/000000000000/households")
    assert resp.status_code in (403, 503)
